from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from app.models.procurement import ProcurementStage, ApprovalStatus, PipelineStatus, EventType


class LineItem(BaseModel):
    item_name: str
    quantity: float
    unit: str
    estimated_price_inr: float | None = None
    required_by: str | None = None


class IntakeRequest(BaseModel):
    buyer_id: str
    natural_language_input: str
    requestor_name: str | None = None
    location: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    purchase_type: str | None = None
    priority: str | None = None
    completion_date: str | None = None
    reason: str | None = None
    preferred_vendors: str | None = None
    preferred_vendor_id: int | None = None
    quotation_received: str | None = None
    line_items: list[dict] | None = None


class ClarificationResponse(BaseModel):
    procurement_id: UUID
    buyer_id: str
    response_text: str


class ApprovalWebhook(BaseModel):
    procurement_id: UUID
    approver_id: str
    decision: str
    notes: str | None = None


class AwardConfirmationWebhook(BaseModel):
    procurement_id: UUID
    buyer_id: str
    confirmed_vendor_id: str


class ProcurementResponse(BaseModel):
    procurement_id: UUID
    current_stage: ProcurementStage
    pipeline_status: PipelineStatus
    approval_status: ApprovalStatus
    buyer_id: str
    intake_record: dict | None
    pr_ids: list[str]
    cart_contents: dict | None
    event_id: str | None
    event_type: EventType | None
    quotes_received: list | None
    negotiation_rounds: int
    awarded_vendor_id: str | None
    po_id: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
