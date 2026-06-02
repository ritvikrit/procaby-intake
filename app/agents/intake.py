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

PROCBAY_HEADERS = {
    "Authorization":  f"Bearer {settings.PROCBAY_TOKEN}",
    "x-api-version":  "1",
    "x-custom-lang":  "en",
    "x-tenant-id":    "vaibhav",
    "Content-Type":   "application/json",
}


class IntakeAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        raw_input = state.get("natural_language_input", "")

        # Use pre-structured data from UI if available
        if state.get("line_items"):
            line_items = [
                {
                    "item_name":            i.get("item_name") or i.get("name", ""),
                    "quantity":             i.get("quantity") or i.get("qty", 1),
                    "unit":                 i.get("unit", "pcs"),
                    "unit_price_inr":       i.get("unit_price_inr") or i.get("price", 0.0),
                    "estimated_price_inr":  i.get("estimated_price_inr", 0.0),
                    "location":             i.get("location", ""),
                }
                for i in state["line_items"]
            ]
            total_value = sum(i["estimated_price_inr"] for i in line_items)

            intake_record = {
                "requestor_name":         state.get("requestor_name"),
                "location":               state.get("location"),
                "department":             state.get("department"),
                "email":                  state.get("email"),
                "phone":                  state.get("phone"),
                "purchase_type":          state.get("purchase_type"),
                "priority":               state.get("priority"),
                "completion_date":        state.get("completion_date"),
                "reason":                 state.get("reason"),
                "preferred_vendors":      state.get("preferred_vendors"),
                "quotation_received":     state.get("quotation_received"),
                "line_items":             line_items,
                "total_estimated_value_inr": total_value,
                "raw_input":              raw_input,
                "deadline":               state.get("completion_date"),
            }

            # ── Push to ProcaBay ───────────────────────────────────────────────
            procbay_ref = await self._push_to_procbay(intake_record)
            if procbay_ref:
                intake_record["procbay_intake_id"] = procbay_ref
            # ──────────────────────────────────────────────────────────────────

            return AgentResult(
                status="SUCCESS",
                updated_fields={"intake_record": intake_record},
                message=f"Structured intake recorded for {len(line_items)} line item(s). Total: ₹{total_value:,.2f}",
                next_stage=ProcurementStage.APPROVALS,
            )

        # Fallback: parse natural language if no structured data provided
        if not raw_input.strip():
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="Please describe what items you need to procure, including quantities and any deadlines.",
            )

        line_items = self._extract_line_items(raw_input)
        total_value = sum(item.get("estimated_price_inr", 0) for item in line_items)

        intake_record = {
            "line_items":                line_items,
            "total_estimated_value_inr": total_value,
            "raw_input":                 raw_input,
            "deadline":                  self._extract_deadline(raw_input),
        }
        return AgentResult(
            status="SUCCESS",
            updated_fields={"intake_record": intake_record},
            message=f"Extracted {len(line_items)} line item(s) from intake.",
            next_stage=ProcurementStage.APPROVALS,
        )

    async def _push_to_procbay(self, intake_record: dict) -> str | None:
        """Push intake data to ProcaBay as form data and return their intake ID."""
        if not settings.PROCBAY_API_URL or not settings.PROCBAY_TOKEN:
            return None

        purchase_type = PURCHASE_TYPE_MAP.get(
            intake_record.get("purchase_type", "Hardware"), "consumables"
        )

        # Convert "27-06-2026" → "2026-06-06"
        completion_date = intake_record.get("completion_date", "")
        if completion_date:
            try:
                d = datetime.strptime(completion_date, "%d-%m-%Y")
                completion_date = d.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Build items in ProcaBay's expected format
        items = [
            {
                "initial_quantity":    i.get("quantity", 1),
                "item_name":           i.get("item_name", ""),
                "price":               i.get("unit_price_inr", 0),
                "unit_of_measurement": i.get("unit", "pcs"),
                "location_id":         1,
            }
            for i in intake_record.get("line_items", [])
        ]

        # Form data payload — matches exactly what ProcaBay's frontend sends
        payload = {
            "business_entity_id":           "1",
            "name_of_entity":               "1",
            "requestor_id":                 "130",
            "department_business_entity":   intake_record.get("department", ""),
            "department":                   intake_record.get("department", "").lower().replace(" ", "-"),
            "contact_information_email":    intake_record.get("email", ""),
            "contact_information_phone_no": intake_record.get("phone", ""),
            "location_name":                intake_record.get("location", ""),
            "request_date":                 datetime.now().strftime("%Y-%m-%d"),
            "purchase_type":                purchase_type,
            "priority":                     intake_record.get("priority", "Medium"),
            "currency":                     "INR",
            "reason_for_purchase":          intake_record.get("reason", ""),
            "service_completion_date":      completion_date,
            "preferred_vendors":            "",
            "have_you_received_a_quotation": "false",
            "type":                         "PURCHASE_INTAKE",
            "items":                        json.dumps(items),
            "estimated_budget":             str(intake_record.get("total_estimated_value_inr", 0)),
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
                    data=payload,   # form data, not json
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
                    "item_name":            name,
                    "quantity":             qty,
                    "unit":                 unit.lower(),
                    "unit_price_inr":       0.0,
                    "estimated_price_inr":  0.0,
                    "required_by":          None,
                })

        if not items:
            items.append({
                "item_name":            text[:200],
                "quantity":             1,
                "unit":                 "pcs",
                "unit_price_inr":       0.0,
                "estimated_price_inr":  0.0,
                "required_by":          None,
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
