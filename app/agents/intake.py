import re
from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage


class IntakeAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        raw_input = state.get("natural_language_input", "")

        if not raw_input.strip():
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="Please describe what items you need to procure, including quantities and any deadlines.",
            )

        line_items = self._extract_line_items(raw_input)
        total_value = sum(item.get("estimated_price_inr", 0) for item in line_items)

        intake_record = {
            "line_items": line_items,
            "total_estimated_value_inr": total_value,
            "raw_input": raw_input,
            "deadline": self._extract_deadline(raw_input),
        }

        return AgentResult(
            status="SUCCESS",
            updated_fields={"intake_record": intake_record},
            message=f"Extracted {len(line_items)} line item(s) from intake.",
            next_stage=ProcurementStage.APPROVALS,
        )

    def _extract_line_items(self, text: str) -> list[dict]:
        items = []
        quantity_pattern = re.compile(
            r"(\d+(?:\.\d+)?)\s*(kg|pcs?|pieces?|units?|boxes?|liters?|l|pairs?|sets?)?\s+(?:of\s+)?([a-zA-Z\s]+?)(?:\s+by|\s+before|\s+within|,|$)",
            re.IGNORECASE,
        )

        for match in quantity_pattern.finditer(text):
            qty = float(match.group(1))
            unit = match.group(2) or "pcs"
            name = match.group(3).strip()
            if name:
                items.append(
                    {
                        "item_name": name,
                        "quantity": qty,
                        "unit": unit.lower(),
                        "estimated_price_inr": 0.0,
                        "required_by": None,
                    }
                )

        if not items:
            items.append(
                {
                    "item_name": text[:200],
                    "quantity": 1,
                    "unit": "pcs",
                    "estimated_price_inr": 0.0,
                    "required_by": None,
                }
            )

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
