from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.procurement import IntakeRequest, ClarificationResponse, ProcurementResponse
from app.orchestrator.engine import OrchestratorEngine
from app.orchestrator.exceptions import HITLRequiredException, ClarificationRequiredException, StageBlockedException
from typing import Optional
from fastapi import Body

router = APIRouter()


@router.post("/", response_model=dict, status_code=201)
async def create_procurement(body: IntakeRequest, db: AsyncSession = Depends(get_db)):
    engine = OrchestratorEngine(db)
    try:
        extra = body.model_dump(exclude={"buyer_id", "natural_language_input"}, exclude_none=True)
        proc = await engine.create_procurement(body.buyer_id, body.natural_language_input, extra)
        return {"procurement_id": str(proc.procurement_id), "status": "CREATED"}
    except HITLRequiredException as e:
        return {"status": "PAUSED_HITL", "message": str(e), "stage": e.stage}
    except ClarificationRequiredException as e:
        return {"status": "PAUSED_CLARIFICATION", "question": e.question, "stage": e.stage}

#not used in ui currentky
@router.get("/{procurement_id}/history")
async def get_history(procurement_id: UUID, db: AsyncSession = Depends(get_db)):
    engine = OrchestratorEngine(db)
    try:
        return await engine.query_history(procurement_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{procurement_id}/advance")
async def advance_stage(
    procurement_id: UUID,
    body: Optional[dict] = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    engine = OrchestratorEngine(db)
    try:
        return await engine.run_stage(procurement_id, extra_context=body or None)
    except HITLRequiredException as e:
        return {"status": "PAUSED_HITL", "message": str(e), "stage": e.stage, "code": 202}
    except ClarificationRequiredException as e:
        return {"status": "PAUSED_CLARIFICATION", "question": e.question, "stage": e.stage, "code": 202}
    except StageBlockedException as e:
        return {"status": "BLOCKED", "message": str(e), "options": e.options, "code": 409}


@router.post("/{procurement_id}/clarify")
async def respond_to_clarification(
    procurement_id: UUID, body: ClarificationResponse, db: AsyncSession = Depends(get_db)
):
    engine = OrchestratorEngine(db)
    try:
        return await engine.handle_clarification_response(procurement_id, body.response_text)
    except ClarificationRequiredException as e:
        return {"status": "PAUSED_CLARIFICATION", "question": e.question, "stage": e.stage}
    except HITLRequiredException as e:
        return {"status": "PAUSED_HITL", "message": str(e), "stage": e.stage}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{procurement_id}/bid")
async def submit_bid(procurement_id: UUID, bid: dict, db: AsyncSession = Depends(get_db)):
    engine = OrchestratorEngine(db)
    try:
        return await engine.handle_bid_submission(procurement_id, bid)
    except HITLRequiredException as e:
        return {"status": "PAUSED_HITL", "message": str(e), "stage": e.stage}
    except ClarificationRequiredException as e:
        return {"status": "PAUSED_CLARIFICATION", "question": e.question, "stage": e.stage}
    except StageBlockedException as e:
        return {"status": "BLOCKED", "message": str(e), "options": e.options}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{procurement_id}/rejection-branch")
async def handle_rejection_branch(
    procurement_id: UUID, body: dict, db: AsyncSession = Depends(get_db)
):
    engine = OrchestratorEngine(db)
    try:
        return await engine.handle_rejection_branch(procurement_id, body.get("branch"))
    except HITLRequiredException as e:
        return {"status": "PAUSED_HITL", "message": str(e), "stage": e.stage}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
