import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class VendorBid(Base):
    __tablename__ = "vendor_bids"

    bid_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    procurement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    vendor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(500), nullable=False)

    unit_price_inr: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    total_price_inr: Mapped[float] = mapped_column(Float, nullable=False)

    delivery_days: Mapped[int | None] = mapped_column(nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    normalized_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    is_active: Mapped[bool] = mapped_column(default=True)
