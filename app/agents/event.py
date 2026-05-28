import uuid
from datetime import datetime, timedelta, timezone
from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage, EventType
from app.config import settings


class EventAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        cart_contents = state.get("cart_contents")
        event_type_str = state.get("requested_event_type", "RFQ")

        if not cart_contents:
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="No cart found. Please complete cart building before configuring sourcing event.",
            )

        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
        event_type = EventType.AUCTION if event_type_str.upper() == "AUCTION" else EventType.RFQ

        updated: dict = {
            "event_id": event_id,
            "event_type": event_type,
        }

        if event_type == EventType.AUCTION:
            duration = state.get("auction_duration_seconds", settings.AUCTION_DEFAULT_DURATION_SECONDS)
            auction_end_time = datetime.now(timezone.utc) + timedelta(seconds=duration)
            updated["auction_end_time"] = auction_end_time.isoformat()

        return AgentResult(
            status="SUCCESS",
            updated_fields=updated,
            message=f"Sourcing event {event_id} ({event_type.value}) configured.",
            next_stage=ProcurementStage.QUOTE,
        )
