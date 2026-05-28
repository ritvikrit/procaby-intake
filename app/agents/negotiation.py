from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage

_MARGIN_DEVIATION_THRESHOLD = 0.15


class NegotiationAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        quotes = state.get("quotes_received") or []
        negotiation_rounds = state.get("negotiation_rounds", 0)
        history = state.get("negotiation_history") or []

        if not quotes:
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="No quotes available for negotiation analysis.",
            )

        sorted_quotes = sorted(quotes, key=lambda q: q.get("total_price_inr", float("inf")))

        if not sorted_quotes:
            return AgentResult(status="ERROR", message="Quote list is empty after sorting.")

        best = sorted_quotes[0]
        avg_price = sum(q.get("total_price_inr", 0) for q in quotes) / len(quotes)

        deviation = (best["total_price_inr"] - avg_price) / avg_price if avg_price else 0

        analysis = {
            "round": negotiation_rounds + 1,
            "best_vendor_id": best["vendor_id"],
            "best_total_inr": best["total_price_inr"],
            "average_bid_inr": avg_price,
            "deviation_pct": round(deviation * 100, 2),
            "counter_offer_suggested": None,
            "recommendation": "",
        }

        if abs(deviation) > _MARGIN_DEVIATION_THRESHOLD:
            counter = best["total_price_inr"] * (1 - _MARGIN_DEVIATION_THRESHOLD)
            analysis["counter_offer_suggested"] = round(counter, 2)
            analysis["recommendation"] = f"Counter-offer ₹{counter:,.0f} to {best['vendor_id']}"
        else:
            analysis["recommendation"] = f"Best bid from {best['vendor_id']} is within threshold. Recommend awarding."

        new_history = list(history) + [analysis]

        return AgentResult(
            status="SUCCESS",
            updated_fields={
                "negotiation_rounds": negotiation_rounds + 1,
                "negotiation_history": new_history,
                "quotes_received": sorted_quotes,
            },
            message=analysis["recommendation"],
            next_stage=ProcurementStage.AWARDING,
        )
