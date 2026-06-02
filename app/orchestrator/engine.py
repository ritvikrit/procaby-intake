import uuid
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.procurement import Procurement, ProcurementStage, PipelineStatus, ApprovalStatus, EventType
from app.models.audit import AuditLog
from app.agents.base import AgentResult
from app.agents.intake import IntakeAgent
from app.agents.approvals import ApprovalsAgent
from app.agents.pr_agent import PRAgent
from app.agents.cart import CartAgent
from app.agents.event import EventAgent
from app.agents.quote import QuoteAgent
from app.agents.negotiation import NegotiationAgent
from app.agents.awarding import AwardingAgent
from app.agents.po import POAgent
from app.orchestrator.exceptions import (
    StageBlockedException, HITLRequiredException, ClarificationRequiredException
)

logger = logging.getLogger(__name__)

STAGE_ORDER = [
    ProcurementStage.INTAKE,
    ProcurementStage.APPROVALS,
    ProcurementStage.PR_GENERATION,
    ProcurementStage.CART,
    ProcurementStage.EVENT,
    ProcurementStage.QUOTE,
    ProcurementStage.NEGOTIATION,
    ProcurementStage.AWARDING,
    ProcurementStage.PO_GENERATION,
    ProcurementStage.CLOSED,
]

AGENT_MAP = {
    ProcurementStage.INTAKE: IntakeAgent,
    ProcurementStage.APPROVALS: ApprovalsAgent,
    ProcurementStage.PR_GENERATION: PRAgent,
    ProcurementStage.CART: CartAgent,
    ProcurementStage.EVENT: EventAgent,
    ProcurementStage.QUOTE: QuoteAgent,
    ProcurementStage.NEGOTIATION: NegotiationAgent,
    ProcurementStage.AWARDING: AwardingAgent,
    ProcurementStage.PO_GENERATION: POAgent,
}


class OrchestratorEngine:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _load_procurement(self, procurement_id: uuid.UUID) -> Procurement:
        result = await self.db.execute(
            select(Procurement).where(Procurement.procurement_id == procurement_id)
        )
        proc = result.scalar_one_or_none()
        if not proc:
            raise ValueError(f"Procurement {procurement_id} not found.")
        return proc

    def _build_state_payload(self, proc: Procurement, extra: dict | None = None) -> dict:
        payload = {
            "procurement_id": str(proc.procurement_id),
            "buyer_id": proc.buyer_id,
            "current_stage": proc.current_stage,
            "intake_record": proc.intake_record or {},
            "approval_status": proc.approval_status.value if proc.approval_status else "PENDING",
            "approval_routing": proc.approval_routing,
            "pr_ids": proc.pr_ids or [],
            "cart_contents": proc.cart_contents,
            "event_id": proc.event_id,
            "event_type": proc.event_type,
            "quotes_received": proc.quotes_received or [],
            "negotiation_rounds": proc.negotiation_rounds,
            "negotiation_history": proc.negotiation_history or [],
            "awarded_vendor_id": proc.awarded_vendor_id,
            "po_id": proc.po_id,
        }
        if extra:
            payload.update(extra)
        return payload

    async def _apply_agent_result(self, proc: Procurement, result: AgentResult) -> None:
        for field, value in result.updated_fields.items():
            if field == "pipeline_status" and isinstance(value, str):
                proc.pipeline_status = PipelineStatus(value)
                continue
            if field == "approval_status" and isinstance(value, str):
                proc.approval_status = ApprovalStatus(value)
                continue
            if field == "auction_end_time" and isinstance(value, str):
                proc.auction_end_time = datetime.fromisoformat(value)
                continue
            if hasattr(proc, field):
                setattr(proc, field, value)
        proc.updated_at = datetime.utcnow()

    async def _log_action(
        self, proc: Procurement, action: str, payload: dict | None = None, actor: str | None = None
    ) -> None:
        log = AuditLog(
            procurement_id=proc.procurement_id,
            stage=proc.current_stage.value,
            action=action,
            actor=actor or proc.buyer_id,
            payload=payload,
        )
        self.db.add(log)

    def _advance_stage(self, current: ProcurementStage) -> ProcurementStage:
        idx = STAGE_ORDER.index(current)
        if idx + 1 < len(STAGE_ORDER):
            return STAGE_ORDER[idx + 1]
        return ProcurementStage.CLOSED

    async def run_stage(
        self,
        procurement_id: uuid.UUID,
        extra_context: dict | None = None,
    ) -> dict:
        proc = await self._load_procurement(procurement_id)

        if proc.pipeline_status == PipelineStatus.CLOSED:
            return {"status": "CLOSED", "message": "Procurement cycle is complete."}

        if proc.pipeline_status == PipelineStatus.CANCELLED:
            return {"status": "CANCELLED", "message": "Procurement was cancelled."}

        if proc.pipeline_status == PipelineStatus.PAUSED_HITL:
            raise HITLRequiredException(
                f"Awaiting human approval at stage {proc.current_stage.value}",
                proc.current_stage.value,
            )

        if proc.pipeline_status == PipelineStatus.PAUSED_CLARIFICATION:
            clarification = proc.pending_clarification or {}
            raise ClarificationRequiredException(
                question=clarification.get("question", "Awaiting clarification."),
                stage=proc.current_stage.value,
            )

        stage = proc.current_stage
        agent_cls = AGENT_MAP.get(stage)

        if not agent_cls:
            return {"status": "CLOSED", "message": "No agent for this stage."}

        agent = agent_cls()
        state_payload = self._build_state_payload(proc, extra_context)

        result: AgentResult = await agent.run(state_payload)

        await self._apply_agent_result(proc, result)
        await self._log_action(proc, f"{stage.value}: {result.message}", payload=result.updated_fields)

        if result.status == "SUCCESS":
            next_stage = result.next_stage or self._advance_stage(stage)
            proc.current_stage = next_stage
            proc.pipeline_status = PipelineStatus.ACTIVE

            if next_stage == ProcurementStage.CLOSED:
                proc.pipeline_status = PipelineStatus.CLOSED
                proc.closed_at = datetime.utcnow()

            await self.db.flush()

            AUTO_CONTINUE = {
                ProcurementStage.PR_GENERATION,
                ProcurementStage.CART,
                ProcurementStage.NEGOTIATION,
            }
            if next_stage in AUTO_CONTINUE:
                return await self.run_stage(procurement_id, extra_context)

            return {
                "status": "SUCCESS",
                "stage": next_stage.value,
                "message": result.message,
            }

        elif result.status == "HITL_REQUIRED":
            proc.pipeline_status = PipelineStatus.PAUSED_HITL
            await self.db.flush()
            raise HITLRequiredException(result.message, stage.value)

        elif result.status == "NEEDS_CLARIFICATION":
            proc.pipeline_status = PipelineStatus.PAUSED_CLARIFICATION
            proc.pending_clarification = {
                "question": result.clarification_question,
                "stage": stage.value,
            }
            await self.db.flush()
            raise ClarificationRequiredException(
                question=result.clarification_question or "Clarification needed.",
                stage=stage.value,
            )

        elif result.status == "BLOCKED":
            proc.pipeline_status = PipelineStatus.PAUSED_HITL
            await self.db.flush()
            raise StageBlockedException(result.message, result.rejection_options)

        else:
            await self._log_action(proc, f"ERROR at {stage.value}: {result.message}")
            raise RuntimeError(f"Agent error at {stage.value}: {result.message}")

    async def create_procurement(self, buyer_id: str, natural_language_input: str, structured_fields: dict | None = None) -> Procurement:
        proc = Procurement(
            buyer_id=buyer_id,
            current_stage=ProcurementStage.INTAKE,
            pipeline_status=PipelineStatus.ACTIVE,
            pr_ids=[],
            quotes_received=[],
            negotiation_history=[],
            negotiation_rounds=0,
            approval_status=ApprovalStatus.PENDING,
        )
        self.db.add(proc)
        await self.db.flush()

        try:
            extra_context = {"natural_language_input": natural_language_input, **(structured_fields or {})}
            await self.run_stage(proc.procurement_id, extra_context=extra_context)
        except (HITLRequiredException, ClarificationRequiredException):
            pass

        await self.db.commit()
        return proc

    async def handle_approval_webhook(
        self, procurement_id: uuid.UUID, approver_id: str, decision: str, notes: str | None = None
    ) -> dict:
        proc = await self._load_procurement(procurement_id)

        if proc.current_stage != ProcurementStage.APPROVALS:
            raise ValueError(f"Procurement is not at APPROVALS stage (current: {proc.current_stage.value}).")

        if decision == "APPROVED":
            routing = proc.approval_routing or {}
            steps = routing.get("steps", [])
            completed = routing.get("completed_steps", [])
            current_step = routing.get("current_step")

            completed.append(current_step)
            remaining = [s for s in steps if s not in completed]

            if remaining:
                routing["current_step"] = remaining[0]
                routing["completed_steps"] = completed
                proc.approval_routing = routing
                proc.pipeline_status = PipelineStatus.PAUSED_HITL
                await self._log_action(proc, f"Partial approval by {approver_id}. Next: {remaining[0]}", actor=approver_id)
                await self.db.commit()
                return {
                    "status": "PARTIAL_APPROVAL",
                    "message": f"Approved by {current_step}. Awaiting {remaining[0]} approval.",
                }
            else:
                proc.approval_status = ApprovalStatus.APPROVED
                proc.pipeline_status = PipelineStatus.ACTIVE
                await self._log_action(proc, f"Final approval by {approver_id}.", actor=approver_id)
                await self.db.flush()
                result = await self.run_stage(procurement_id)
                await self.db.commit()
                return result

        elif decision == "REJECTED":
            proc.approval_status = ApprovalStatus.REJECTED
            proc.pipeline_status = PipelineStatus.PAUSED_HITL
            await self._log_action(proc, f"Rejected by {approver_id}. Notes: {notes}", actor=approver_id)
            await self.db.commit()
            raise StageBlockedException(
                "Procurement request was rejected.",
                options=["REVISE_REQUEST", "ESCALATE_ROUTING", "CANCEL_PROCUREMENT"],
            )

        else:
            raise ValueError(f"Unknown decision: {decision}")

    async def handle_clarification_response(
        self, procurement_id: uuid.UUID, response_text: str
    ) -> dict:
        proc = await self._load_procurement(procurement_id)

        if proc.pipeline_status != PipelineStatus.PAUSED_CLARIFICATION:
            raise ValueError("Procurement is not awaiting clarification.")

        proc.pipeline_status = PipelineStatus.ACTIVE
        proc.pending_clarification = None
        await self.db.flush()

        result = await self.run_stage(
            procurement_id,
            extra_context={"clarification_response": response_text, "natural_language_input": response_text},
        )
        await self.db.commit()
        return result

    async def handle_award_confirmation(
        self, procurement_id: uuid.UUID, confirmed_vendor_id: str
    ) -> dict:
        proc = await self._load_procurement(procurement_id)

        if proc.current_stage != ProcurementStage.AWARDING:
            raise ValueError(f"Not at AWARDING stage (current: {proc.current_stage.value}).")

        proc.pipeline_status = PipelineStatus.ACTIVE
        await self.db.flush()

        result = await self.run_stage(
            procurement_id,
            extra_context={"confirmed_vendor_id": confirmed_vendor_id},
        )
        await self.db.commit()
        return result

    async def handle_bid_submission(
        self, procurement_id: uuid.UUID, bid: dict
    ) -> dict:
        proc = await self._load_procurement(procurement_id)

        if proc.current_stage not in (ProcurementStage.QUOTE, ProcurementStage.EVENT):
            raise ValueError(f"Not accepting bids at stage {proc.current_stage.value}.")

        proc.current_stage = ProcurementStage.QUOTE
        proc.pipeline_status = PipelineStatus.ACTIVE
        await self.db.flush()

        result = await self.run_stage(
            procurement_id,
            extra_context={"incoming_bids": [bid]},
        )
        await self.db.commit()
        return result

    async def handle_rejection_branch(
        self, procurement_id: uuid.UUID, branch: str
    ) -> dict:
        proc = await self._load_procurement(procurement_id)

        if branch == "CANCEL_PROCUREMENT":
            proc.pipeline_status = PipelineStatus.CANCELLED
            proc.closed_at = datetime.utcnow()
            await self._log_action(proc, "Procurement cancelled by buyer.")
            await self.db.commit()
            return {"status": "CANCELLED", "message": "Procurement cancelled."}

        elif branch == "REVISE_REQUEST":
            proc.current_stage = ProcurementStage.INTAKE
            proc.pipeline_status = PipelineStatus.ACTIVE
            proc.approval_status = ApprovalStatus.PENDING
            proc.approval_routing = None
            await self._log_action(proc, "Procurement revision requested.")
            await self.db.flush()
            result = await self.run_stage(procurement_id)
            await self.db.commit()
            return result

        elif branch == "ESCALATE_ROUTING":
            routing = proc.approval_routing or {}
            if "CFO" not in routing.get("steps", []):
                routing["steps"] = routing.get("steps", []) + ["CFO"]
            routing["current_step"] = "CFO"
            proc.approval_routing = routing
            proc.approval_status = ApprovalStatus.PENDING
            proc.pipeline_status = PipelineStatus.PAUSED_HITL
            proc.current_stage = ProcurementStage.APPROVALS
            await self._log_action(proc, "Approval escalated to CFO.")
            await self.db.commit()
            raise HITLRequiredException("Escalated to CFO for approval.", ProcurementStage.APPROVALS.value)

        else:
            raise ValueError(f"Unknown branch: {branch}")

    async def query_history(self, procurement_id: uuid.UUID) -> dict:
        proc = await self._load_procurement(procurement_id)
        return {
            "procurement_id": str(proc.procurement_id),
            "current_stage": proc.current_stage.value,
            "pipeline_status": proc.pipeline_status.value,
            "intake_record": proc.intake_record,
            "approval_status": proc.approval_status.value,
            "pr_ids": proc.pr_ids,
            "cart_contents": proc.cart_contents,
            "event_id": proc.event_id,
            "event_type": proc.event_type.value if proc.event_type else None,
            "quotes_received": proc.quotes_received,
            "negotiation_rounds": proc.negotiation_rounds,
            "awarded_vendor_id": proc.awarded_vendor_id,
            "po_id": proc.po_id,
            "created_at": proc.created_at.isoformat() if proc.created_at else None,
            "updated_at": proc.updated_at.isoformat() if proc.updated_at else None,
        }
