import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import String, Integer, DateTime, Enum as PGEnum, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ProcurementStage(str, Enum):
    INTAKE = "INTAKE"
    APPROVALS = "APPROVALS"
    PR_GENERATION = "PR_GENERATION"
    CART = "CART"
    EVENT = "EVENT"
    QUOTE = "QUOTE"
    NEGOTIATION = "NEGOTIATION"
    AWARDING = "AWARDING"
    PO_GENERATION = "PO_GENERATION"
    CLOSED = "CLOSED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_REQUIRED = "NOT_REQUIRED"


class PipelineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED_HITL = "PAUSED_HITL"
    PAUSED_CLARIFICATION = "PAUSED_CLARIFICATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    RFQ = "RFQ"
    AUCTION = "AUCTION"


class Procurement(Base):
    __tablename__ = "procurements"

    procurement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    current_stage: Mapped[ProcurementStage] = mapped_column(
        PGEnum(ProcurementStage), nullable=False, default=ProcurementStage.INTAKE
    )
    pipeline_status: Mapped[PipelineStatus] = mapped_column(
        PGEnum(PipelineStatus), nullable=False, default=PipelineStatus.ACTIVE
    )
    buyer_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stage 1 — Intake
    intake_record: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Stage 2 — Approvals
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        PGEnum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING
    )
    approval_routing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Stage 3 — PR
    pr_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # Stage 4 — Cart
    cart_contents: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Stage 5 — Event
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[EventType | None] = mapped_column(PGEnum(EventType), nullable=True)
    auction_end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Stage 6 — Quotes
    quotes_received: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # Stage 7 — Negotiation
    negotiation_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    negotiation_history: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # Stage 8 — Awarding
    awarded_vendor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Stage 9 — PO
    po_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Clarification handling
    pending_clarification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"), onupdate=datetime.utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
