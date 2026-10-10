"""Use the writer's server grounding as the financial review evidence contract."""

from copy import deepcopy

from app.core.citations import compact_evidence
from app.core.education_grounding import EducationGroundingSnapshot
from app.core.financial_grounding import FinancialGroundingSnapshot, fingerprint
from app.core.telemetry import log_event
from app.models.gateway import ModelGatewayError


def financial_review_evidence(result):
    log_event("VV entering ", "app.core.review_evidence", "financial_review_evidence")
    snapshot = result._financial_grounding_snapshot
    if not isinstance(snapshot, FinancialGroundingSnapshot):
        return None
    if fingerprint(snapshot.grounding) != snapshot.grounding_hash or fingerprint(result.data) != snapshot.grounding_hash:
        raise ModelGatewayError("Financial review authority changed.",
                                code="INVALID_FINANCIAL_REPAIR_CONTEXT", component=result.agent.value)
    return deepcopy(snapshot.grounding)


def review_evidence(result, presentation_fields):
    log_event("VV entering ", "app.core.review_evidence", "review_evidence")
    if isinstance(result._education_grounding_snapshot, EducationGroundingSnapshot):
        result._education_grounding_snapshot.for_review(result.data)
    financial = financial_review_evidence(result)
    data = financial if financial is not None else {
        key: result.data[key] for key in presentation_fields if key in result.data
    }
    if "general_knowledge" in data:
        data["general_knowledge"] = [{"topic": item["topic"]} for item in data["general_knowledge"]]
    return compact_evidence(data)


def grounding_evidence_refs(results):
    log_event("VV entering ", "app.core.review_evidence", "grounding_evidence_refs")
    refs = {
        f"{result.agent.value}.{key}": result.agent.value
        for result in results
        for key in (financial_review_evidence(result) or {})
    }
    for result in results:
        if isinstance(result._education_grounding_snapshot, EducationGroundingSnapshot):
            grounding = result._education_grounding_snapshot.for_review(result.data)
            refs.update({f"{result.agent.value}.{key}": result.agent.value
                         for key in ("contexts", "sources", "subquestion_coverage", "coverage_assessment",
                                     "fallback_topics", "excluded_topics") if key in grounding})
    return refs
