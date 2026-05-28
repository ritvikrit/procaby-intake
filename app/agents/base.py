from dataclasses import dataclass, field
from typing import Literal
from app.models.procurement import ProcurementStage


@dataclass
class AgentResult:
    status: Literal["SUCCESS", "NEEDS_CLARIFICATION", "BLOCKED", "ERROR", "HITL_REQUIRED"]
    updated_fields: dict = field(default_factory=dict)
    clarification_question: str | None = None
    message: str = ""
    next_stage: ProcurementStage | None = None
    rejection_options: list[str] | None = None


class BaseAgent:
    async def run(self, state: dict) -> AgentResult:
        raise NotImplementedError
