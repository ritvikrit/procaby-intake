from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.procurement import ApprovalWebhook, AwardConfirmationWebhook
from app.orchestrator.engine import OrchestratorEngine
from app.orchestrator.exceptions import HITLRequiredException, StageBlockedException, ClarificationRequiredException

router = APIRouter()


@router.post("/approval")
async def approval_webhook(body: ApprovalWebhook, db: AsyncSession = Depends(get_db)):
    engine = OrchestratorEngine(db)
    try:
        return await engine.handle_approval_webhook(
            body.procurement_id, body.approver_id, body.decision, body.notes
        )
    except StageBlockedException as e:
        return {
            "status": "REJECTED",
            "message": str(e),
            "options": e.options,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/award-confirmation")
async def award_confirmation(body: AwardConfirmationWebhook, db: AsyncSession = Depends(get_db)):
    engine = OrchestratorEngine(db)
    try:
        return await engine.handle_award_confirmation(body.procurement_id, body.confirmed_vendor_id)
    except HITLRequiredException as e:
        return {"status": "PAUSED_HITL", "message": str(e), "stage": e.stage}
    except ClarificationRequiredException as e:
        return {"status": "PAUSED_CLARIFICATION", "question": e.question, "stage": e.stage}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
