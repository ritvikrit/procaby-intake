from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage


class QuoteAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        event_id = state.get("event_id")
        raw_bids = state.get("incoming_bids", [])
        existing_quotes = state.get("quotes_received") or []

        if not event_id:
            return AgentResult(status="ERROR", message="No event_id found for quote collection.")

        if not raw_bids:
            return AgentResult(
                status="SUCCESS",
                updated_fields={"quotes_received": existing_quotes},
                message="No new bids to normalize.",
                next_stage=None,
            )

        normalized = [self._normalize_bid(bid) for bid in raw_bids]
        all_quotes: dict[str, dict] = {q["vendor_id"]: q for q in existing_quotes}
        for bid in normalized:
            all_quotes[bid["vendor_id"]] = bid

        merged_quotes = list(all_quotes.values())

        return AgentResult(
            status="SUCCESS",
            updated_fields={"quotes_received": merged_quotes},
            message=f"Normalized {len(normalized)} new bid(s). Total: {len(merged_quotes)} vendor(s).",
            next_stage=ProcurementStage.QUOTE,
        )

    def _normalize_bid(self, raw: dict) -> dict:
        return {
            "vendor_id": str(raw.get("vendor_id", raw.get("supplierId", raw.get("id", "UNKNOWN")))),
            "vendor_name": str(raw.get("vendor_name", raw.get("supplierName", raw.get("name", "Unknown")))),
            "unit_price_inr": float(raw.get("unit_price_inr", raw.get("unitPrice", raw.get("price", 0)))),
            "quantity": float(raw.get("quantity", raw.get("qty", 1))),
            "total_price_inr": float(
                raw.get("total_price_inr", raw.get("totalPrice", 0))
                or (
                    float(raw.get("unit_price_inr", raw.get("unitPrice", raw.get("price", 0))))
                    * float(raw.get("quantity", raw.get("qty", 1)))
                )
            ),
            "delivery_days": int(raw.get("delivery_days", raw.get("deliveryDays", raw.get("lead_time", 0)))),
            "currency": "INR",
            "submitted_at": raw.get("submitted_at", str(datetime.utcnow())),
        }


from datetime import datetime
