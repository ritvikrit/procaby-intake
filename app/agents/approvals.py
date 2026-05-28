from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage, ApprovalStatus
from app.config import settings


class ApprovalsAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        intake_record = state.get("intake_record", {})
        total_value = intake_record.get("total_estimated_value_inr", 0)
        approval_status = state.get("approval_status", "PENDING")

        if approval_status == ApprovalStatus.APPROVED:
            return AgentResult(
                status="SUCCESS",
                updated_fields={},
                message="Approval already granted. Proceeding to PR generation.",
                next_stage=ProcurementStage.PR_GENERATION,
            )

        if approval_status == ApprovalStatus.REJECTED:
            return AgentResult(
                status="BLOCKED",
                message="Procurement request was rejected.",
                rejection_options=["REVISE_REQUEST", "ESCALATE_ROUTING", "CANCEL_PROCUREMENT"],
            )

        if total_value > settings.CFO_THRESHOLD_INR:
            routing = {
                "tier": "SEQUENTIAL",
                "steps": ["MANAGER", "CFO"],
                "current_step": "MANAGER",
                "completed_steps": [],
            }
        else:
            routing = {
                "tier": "SINGLE",
                "steps": ["MANAGER"],
                "current_step": "MANAGER",
                "completed_steps": [],
            }

        return AgentResult(
            status="HITL_REQUIRED",
            updated_fields={
                "approval_routing": routing,
                "approval_status": ApprovalStatus.PENDING,
            },
            message=f"Approval required: {routing['tier']} routing for ₹{total_value:,.0f}. Awaiting human sign-off.",
        )
