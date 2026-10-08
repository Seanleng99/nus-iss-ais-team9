"""Use the writer's server grounding as the financial review evidence contract."""

from copy import deepcopy

from app.core.citations import compact_evidence
from app.core.financial_grounding import FinancialGroundingSnapshot, fingerprint
from app.models.gateway import ModelGatewayError


def financial_review_evidence(result):
    snapshot = result._financial_grounding_snapshot
    if not isinstance(snapshot, FinancialGroundingSnapshot):
        return None
    if fingerprint(snapshot.grounding) != snapshot.grounding_hash or fingerprint(result.data) != snapshot.grounding_hash:
        raise ModelGatewayError("Financial review authority changed.",
                                code="INVALID_FINANCIAL_REPAIR_CONTEXT", component=result.agent.value)
    return deepcopy(snapshot.grounding)


def review_evidence(result, presentation_fields):
    financial = financial_review_evidence(result)
    data = financial if financial is not None else {
        key: result.data[key] for key in presentation_fields if key in result.data
    }
    if "general_knowledge" in data:
        data["general_knowledge"] = [{"topic": item["topic"]} for item in data["general_knowledge"]]
    return compact_evidence(data)


def financial_evidence_refs(results):
    return {
        f"{result.agent.value}.{key}": result.agent.value
        for result in results
        for key in (financial_review_evidence(result) or {})
    }
