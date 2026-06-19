import re
import json
import httpx
from datetime import datetime, timezone
from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage
from app.config import settings

# Map UI purchase type values to ProcaBay accepted values
PURCHASE_TYPE_MAP = {
    "Hardware":             "consumables",
    "Software":             "services",
    "Services":             "services",
    "Consumables":          "consumables",
    "Capital Expenditure":  "capital_expenditure",
    "Operational":          "operational_expenditure",
}

# ProcaBay locations from GET /api/v1/location/dropdown
PROCBAY_LOCATIONS = {
    "Pune Office":   {"id": 1, "name": "Pune Office"},
    "Pune Office 2": {"id": 2, "name": "Pune Office 2"},
    "Magarpatta":    {"id": 3, "name": "Magarpatta"},
    "kharadi":       {"id": 4, "name": "kharadi"},
    "Hinjawdi":      {"id": 5, "name": "Hinjawdi"},
    "Narhe":         {"id": 6, "name": "Narhe"},
}

CLAUDE_SYSTEM_PROMPT = """You are a procurement intake parser. Extract structured information from purchase request text and return ONLY valid JSON with no extra text.

Return this exact structure:
{
  "line_items": [
    {
      "item_name": "string",
      "quantity": number,
      "unit": "pcs",
      "estimated_price_inr": 0.0
    }
  ],
  "deadline": "string or null",
  "priority": "Urgent or High or Medium or Low",
  "location": "string or null",
  "reason": "string or null"
}

Rules:
- Extract every item mentioned with its quantity
- If no quantity is mentioned, default to 1
- If no unit is mentioned, use "pcs"
- Priority defaults to "Medium" if not mentioned
- estimated_price_inr is always 0.0 unless explicitly stated
- Return only the JSON object, nothing else"""


class IntakeAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        raw_input = state.get("natural_language_input", "")

        # ── Structured path: UI submitted rich form data ───────────────────────
        if state.get("line_items"):
            line_items = [
                {
                    "item_name":            i.get("item_name") or i.get("name", ""),
                    "quantity":             i.get("quantity") or i.get("qty", 1),
                    "unit":                 i.get("unit", "pcs"),
                    "unit_price_inr":       i.get("unit_price_inr") or i.get("price", 0.0),
                    "estimated_price_inr":  i.get("estimated_price_inr", 0.0),
                    "location":             i.get("location", ""),
                    "procbay_id":           i.get("procbay_id"),
                }
                for i in state["line_items"]
            ]
            total_value = sum(i["estimated_price_inr"] for i in line_items)

            intake_record = {
                "requestor_name":            state.get("requestor_name"),
                "location":                  state.get("location"),
                "department":                state.get("department"),
                "email":                     state.get("email"),
                "phone":                     state.get("phone"),
                "purchase_type":             state.get("purchase_type"),
                "priority":                  state.get("priority"),
                "completion_date":           state.get("completion_date"),
                "reason":                    state.get("reason"),
                "preferred_vendors":         state.get("preferred_vendors"),
                "preferred_vendor_id":       state.get("preferred_vendor_id"),
                "quotation_received":        state.get("quotation_received"),
                "line_items":                line_items,
                "total_estimated_value_inr": total_value,
                "raw_input":                 raw_input,
                "deadline":                  state.get("completion_date"),
                "parsed_by":                 "structured_form",
            }

            procbay_ref = await self._push_to_procbay(intake_record)
            if procbay_ref:
                intake_record["procbay_intake_id"] = procbay_ref

            return AgentResult(
                status="SUCCESS",
                updated_fields={"intake_record": intake_record},
                message=f"Structured intake recorded for {len(line_items)} line item(s). Total: ₹{total_value:,.2f}",
                next_stage=ProcurementStage.APPROVALS,
            )

        # ── NL fallback: try Claude first, then regex ──────────────────────────
        if not raw_input.strip():
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="Please describe what items you need to procure, including quantities and any deadlines.",
            )

        parsed = await self._parse_with_claude(raw_input)

        if parsed:
            line_items  = parsed.get("line_items", [])
            total_value = sum(i.get("estimated_price_inr", 0) for i in line_items)
            intake_record = {
                "line_items":                line_items,
                "total_estimated_value_inr": total_value,
                "raw_input":                 raw_input,
                "deadline":                  parsed.get("deadline"),
                "priority":                  parsed.get("priority", "Medium"),
                "location":                  parsed.get("location"),
                "reason":                    parsed.get("reason"),
                "parsed_by":                 "claude",
            }
            return AgentResult(
                status="SUCCESS",
                updated_fields={"intake_record": intake_record},
                message=f"Claude extracted {len(line_items)} line item(s) from intake.",
                next_stage=ProcurementStage.APPROVALS,
            )

        # ── Regex fallback if Claude unavailable ───────────────────────────────
        line_items  = self._extract_line_items(raw_input)
        total_value = sum(i.get("estimated_price_inr", 0) for i in line_items)
        intake_record = {
            "line_items":                line_items,
            "total_estimated_value_inr": total_value,
            "raw_input":                 raw_input,
            "deadline":                  self._extract_deadline(raw_input),
            "parsed_by":                 "regex",
        }
        return AgentResult(
            status="SUCCESS",
            updated_fields={"intake_record": intake_record},
            message=f"Regex extracted {len(line_items)} line item(s) from intake.",
            next_stage=ProcurementStage.APPROVALS,
        )

    async def _parse_with_claude(self, raw_input: str) -> dict | None:
        """Use OpenAI to parse natural language into structured intake data."""
        import os
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": CLAUDE_SYSTEM_PROMPT},
                    {"role": "user", "content": raw_input},
                ],
            )
            text = response.choices[0].message.content.strip()
            return json.loads(text)
        except Exception as e:
            print(f"[OpenAI] WARNING: Failed to parse intake — {e}")
            return None

    async def _push_to_procbay(self, intake_record: dict) -> str | None:
        """Push intake data to ProcaBay as form data and return their intake ID."""
        print(f"[ProcaBay] URL={settings.PROCBAY_API_URL} TOKEN={bool(settings.PROCBAY_TOKEN)}")
        if not settings.PROCBAY_API_URL or not settings.PROCBAY_TOKEN:
            print("[ProcaBay] Skipping — URL or TOKEN not set")
            return None

        purchase_type = PURCHASE_TYPE_MAP.get(
            intake_record.get("purchase_type", "Hardware"), "consumables"
        )

        completion_date = intake_record.get("completion_date", "")
        if completion_date:
            try:
                d = datetime.strptime(completion_date, "%d-%m-%Y")
                completion_date = d.strftime("%Y-%m-%d")
            except ValueError:
                pass

        department  = intake_record.get("department", "Engineering")
        location    = intake_record.get("location", "")
        tenant_name = "Katalyst Technologies"

        # Resolve ProcaBay location
        procbay_loc = PROCBAY_LOCATIONS.get(location, {"id": 3, "name": location})
        location_id = procbay_loc["id"]
        location_name = procbay_loc["name"]

        # Build items in ProcaBay's exact format
        items = []
        for i in intake_record.get("line_items", []):
            item = {
                "initial_quantity":    i.get("quantity", 1),
                "item_name":           i.get("item_name", ""),
                "price":               i.get("unit_price_inr", 0),
                "unit_of_measurement": i.get("unit", "pcs"),
                "location_id":         location_id,
            }
            procbay_id = i.get("procbay_id") or i.get("id")
            if procbay_id:
                item["id"] = procbay_id
            items.append(item)

        vendor_id = intake_record.get("preferred_vendor_id", "")

        quotation_received = "true" if intake_record.get("quotation_received", "no").lower() == "yes" else "false"

        payload = {
            "type":                          "PURCHASE_INTAKE",
            "requestor_id":                  "50",
            "department":                    "katalyst-technologies-operations",
            "contact_information":           intake_record.get("email", ""),
            "contact_information_phone_no":  intake_record.get("phone", "").replace("+", "").replace(" ", ""),
            "location_name":                 location_name,
            "request_date":                  datetime.now().strftime("%Y-%m-%d"),
            "purchase_type":                 purchase_type,
            "priority":                      intake_record.get("priority", "Medium"),
            "estimated_budget":              str(intake_record.get("total_estimated_value_inr", 0)),
            "currency":                      "INR",
            "required_delivery":             completion_date,
            "reason_for_purchase":           intake_record.get("reason", ""),
            "preferred_vendors":             intake_record.get("preferred_vendors", ""),
            "have_you_received_a_quotation": quotation_received,
            "items":                         json.dumps(items),
        }

        headers = {
            "Authorization": f"Bearer {settings.PROCBAY_TOKEN}",
            "x-api-version": "1",
            "x-custom-lang": "en",
            "x-tenant-id":   "vaibhav",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.PROCBAY_API_URL}/purchase-intakes/create-purchase-intakes",
                    data=payload,
                    files={
                        "attachments":              ("", b"", "application/octet-stream"),
                        "if_yes_attach_quotations": ("", b"", "application/octet-stream"),
                    },
                    headers=headers,
                    timeout=15.0,
                )
                print(f"[ProcaBay] Status: {resp.status_code}")
                print(f"[ProcaBay] Response: {resp.text}")
                resp.raise_for_status()
                data = resp.json()
                return str(data.get("data", {}).get("id", ""))
        except Exception as e:
            print(f"[ProcaBay] WARNING: Failed to push intake — {e}")
            return None

    def _extract_line_items(self, text: str) -> list[dict]:
        items = []
        quantity_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*(kg|pcs?|pieces?|units?|boxes?|liters?|l|pairs?|sets?)?\s+(?:of\s+)?([a-zA-Z\s]+?)(?:\s+by|\s+before|\s+within|,|$)",
            re.IGNORECASE,
        )
        for match in quantity_pattern.finditer(text):
            qty  = float(match.group(1))
            unit = match.group(2) or "pcs"
            name = match.group(3).strip()
            if name:
                items.append({
                    "item_name":           name,
                    "quantity":            qty,
                    "unit":                unit.lower(),
                    "unit_price_inr":      0.0,
                    "estimated_price_inr": 0.0,
                    "required_by":         None,
                })
        if not items:
            items.append({
                "item_name":           text[:200],
                "quantity":            1,
                "unit":                "pcs",
                "unit_price_inr":      0.0,
                "estimated_price_inr": 0.0,
                "required_by":         None,
            })
        return items

    def _extract_deadline(self, text: str) -> str | None:
        deadline_patterns = [
            r"by\s+(end of (?:this |next )?(?:week|month|quarter|year))",
            r"within\s+(\d+\s+(?:days?|weeks?|months?))",
            r"before\s+(\w+ \d+)",
        ]
        for pattern in deadline_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
