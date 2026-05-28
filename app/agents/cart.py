import uuid
from app.agents.base import BaseAgent, AgentResult
from app.models.procurement import ProcurementStage


class CartAgent(BaseAgent):
    async def run(self, state: dict) -> AgentResult:
        pr_ids = state.get("pr_ids", [])
        intake_record = state.get("intake_record", {})

        if not pr_ids:
            return AgentResult(
                status="NEEDS_CLARIFICATION",
                clarification_question="No Purchase Requisitions found to build a cart from.",
            )

        cart_id = f"CART-{uuid.uuid4().hex[:8].upper()}"
        all_line_items = intake_record.get("line_items", [])

        merged: dict[str, dict] = {}
        for item in all_line_items:
            key = item["item_name"].lower().strip()
            if key in merged:
                merged[key]["quantity"] += item["quantity"]
            else:
                merged[key] = dict(item)

        cart_contents = {
            "cart_id": cart_id,
            "pr_ids": pr_ids,
            "line_items": list(merged.values()),
            "total_line_items": len(merged),
            "total_estimated_value_inr": sum(
                i.get("estimated_price_inr", 0) * i.get("quantity", 1) for i in merged.values()
            ),
        }

        return AgentResult(
            status="SUCCESS",
            updated_fields={"cart_contents": cart_contents},
            message=f"Cart {cart_id} built with {len(merged)} unique line item(s) across {len(pr_ids)} PR(s).",
            next_stage=ProcurementStage.EVENT,
        )
