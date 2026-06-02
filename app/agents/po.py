import uuid
from datetime import datetime
import httpx   
from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage, PipelineStatus
from app.config import settings     

class POAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        awarded_vendor_id = state.get("awarded_vendor_id")
        pr_ids = state.get("pr_ids", [])
        quotes = state.get("quotes_received") or []
        intake_record = state.get("intake_record", {})

        if not awarded_vendor_id:
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="No awarded vendor found. Awarding stage must be completed first.",
            )

        winning_bid = next((q for q in quotes if q.get("vendor_id") == awarded_vendor_id), None)

        po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"

        po_record = {
            "po_id": po_id,
            "awarded_vendor_id": awarded_vendor_id,
            "vendor_name": winning_bid.get("vendor_name") if winning_bid else "Unknown",
            "pr_ids": pr_ids,
            "line_items": intake_record.get("line_items", []),
            "total_amount_inr": winning_bid.get("total_price_inr", 0) if winning_bid else 0,
            "delivery_days": winning_bid.get("delivery_days") if winning_bid else None,
            "currency": "INR",
            "generated_at": str(datetime.utcnow()),
            "status": "ISSUED",
        }
          # ── Push to ProcaBay ──────────────────────────────────────────
        if settings.PROCBAY_TOKEN:
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://api.procbay.com/purchase-orders",  # their endpoint
                    json=po_record,
                    headers={"Authorization": settings.PROCBAY_TOKEN},
                    timeout=10.0,
                )
        # ─────────────────────────────────────────────────────────────


        return AgentResult(
            status="SUCCESS",
            updated_fields={
                "po_id": po_id,
                "pipeline_status": PipelineStatus.CLOSED,
            },
            message=f"Purchase Order {po_id} issued. Procurement cycle CLOSED.",
            next_stage=ProcurementStage.CLOSED,
        )
