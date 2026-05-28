class RejectionBranch(str):
    REVISE_REQUEST = "REVISE_REQUEST"
    ESCALATE_ROUTING = "ESCALATE_ROUTING"
    CANCEL_PROCUREMENT = "CANCEL_PROCUREMENT"


class OrchestratorException(Exception):
    pass


class StageBlockedException(OrchestratorException):
    def __init__(self, message: str, options: list[str] | None = None):
        super().__init__(message)
        self.options = options or []


class HITLRequiredException(OrchestratorException):
    def __init__(self, message: str, stage: str):
        super().__init__(message)
        self.stage = stage


class ClarificationRequiredException(OrchestratorException):
    def __init__(self, question: str, stage: str):
        super().__init__(question)
        self.question = question
        self.stage = stage
