from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage


class AwardingAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        quotes = state.get("quotes_received") or []
        confirmed_vendor_id = state.get("confirmed_vendor_id")
        awarded_vendor_id = state.get("awarded_vendor_id")

        if confirmed_vendor_id:
            return AgentResult(
                status="SUCCESS",
                updated_fields={"awarded_vendor_id": confirmed_vendor_id},
                message=f"Award confirmed for vendor {confirmed_vendor_id}.",
                next_stage=ProcurementStage.PO_GENERATION,
            )

        if not quotes:
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="No quotes available to evaluate for award selection.",
            )

        sorted_quotes = sorted(quotes, key=lambda q: q.get("total_price_inr", float("inf")))
        best = sorted_quotes[0]

        return AgentResult(
            status="HITL_REQUIRED",
            updated_fields={"awarded_vendor_id": best["vendor_id"]},
            message=(
                f"Recommended award: {best['vendor_name']} at ₹{best['total_price_inr']:,.0f}. "
                f"Awaiting buyer confirmation."
            ),
        )
