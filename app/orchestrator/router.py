from app.models.procurement import ProcurementStage

STAGE_ROUTE = {
    ProcurementStage.INTAKE: ProcurementStage.APPROVALS,
    ProcurementStage.APPROVALS: ProcurementStage.PR_GENERATION,
    ProcurementStage.PR_GENERATION: ProcurementStage.CART,
    ProcurementStage.CART: ProcurementStage.EVENT,
    ProcurementStage.EVENT: ProcurementStage.QUOTE,
    ProcurementStage.QUOTE: ProcurementStage.NEGOTIATION,
    ProcurementStage.NEGOTIATION: ProcurementStage.AWARDING,
    ProcurementStage.AWARDING: ProcurementStage.PO_GENERATION,
    ProcurementStage.PO_GENERATION: ProcurementStage.CLOSED,
}


def next_stage(current: ProcurementStage) -> ProcurementStage:
    return STAGE_ROUTE.get(current, ProcurementStage.CLOSED)
