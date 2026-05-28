import uuid
from datetime import datetime
from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage


class PRAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        intake_record = state.get("intake_record", {})
        line_items = intake_record.get("line_items", [])

        if not line_items:
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="No line items found in the intake record. Please verify your procurement request.",
            )

        pr_id = f"PR-{uuid.uuid4().hex[:8].upper()}"

        pr_record = {
            "pr_id": pr_id,
            "line_items": line_items,
            "buyer_id": state.get("buyer_id"),
            "total_estimated_value_inr": intake_record.get("total_estimated_value_inr", 0),
            "generated_at": str(datetime.utcnow()),
            "status": "OPEN",
        }

        return AgentResult(
            status="SUCCESS",
            updated_fields={"pr_ids": [pr_id]},
            message=f"Generated PR: {pr_id}",
            next_stage=ProcurementStage.CART,
        )
