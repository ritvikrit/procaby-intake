from pydantic import BaseModel
from typing import Literal


class WSMessage(BaseModel):
    type: Literal[
        "BID_UPDATE", "AUCTION_TICK", "AUCTION_CLOSED", "STAGE_TRANSITION",
        "HITL_REQUIRED", "CLARIFICATION_REQUIRED", "ERROR"
    ]
    procurement_id: str
    payload: dict | None = None
