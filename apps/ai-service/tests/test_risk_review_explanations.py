"""Explain failures without releasing rejected prose or weakening evidence gates."""

import json

import pytest
from test_risk_compliance import _BlockingReviewGateway, _DecisionGateway, _RecordingGateway

from app.agents.base import BaseAgent
from app.agents.risk_compliance import RiskComplianceAgent, withhold_agent_result
from app.core.config import Settings
from app.core.financial_grounding import FinancialGroundingSnapshot
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentName, AgentResult, AgentTask, CoachRequest
from app.orchestrator import AgentOrchestrator
from app.rag.local_policy import LocalDocumentPolicyRetriever


def test_review_failure_is_explained_without_releasing_rejected_prose():
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=_BlockingReviewGateway(), policy_retriever=LocalDocumentPolicyRetriever(),
    ).handle(CoachRequest(user_id="synthetic", session_id="explanation",
                          message="Explain zero-based budgeting in general."))
    assert response.blocked
    assert "review failure" in response.answer
    assert "not a finding that your question is prohibited" in response.answer
    review = next(item for item in response.agent_results if item.agent == AgentName.RISK_COMPLIANCE)
    assert review.data["validation_reason"] == "STRUCTURED_SCHEMA_INVALID"
    assert review.data["block_reasons"] == ["review_contract_unverified"]
    event = next(item for item in response.audit["events"] if item["event_type"] == "compliance.completed")
    assert event["details"]["validation_reason"] == "STRUCTURED_SCHEMA_INVALID"
    assert "The draft was not approved" not in response.model_dump_json()


@pytest.mark.parametrize(("changes", "reason"), [
    ({"section_id": "unknown"}, "REVIEW_UNKNOWN_SECTION"),
    ({"category": "citation_attribution"}, "REVIEW_CATEGORY_MISMATCH"),
    ({"claim_quote": "Absent private claim"}, "REVIEW_CLAIM_NOT_UNIQUE"),
    ({"claim_start": 1, "claim_end": 20}, "REVIEW_CLAIM_OFFSET_MISMATCH"),
    ({"claim_quote": None}, "REVIEW_CLAIM_LOCATION_REQUIRED"),
    ({"evidence_refs": ["goal_strategy.projections"]}, "REVIEW_FOREIGN_EVIDENCE_REF"),
    ({"claim_quote": None, "claim_start": 0, "claim_end": 200}, "REVIEW_INVALID_CLAIM_RANGE"),
])
def test_invalid_review_records_exact_safe_validation_reason(changes, reason, caplog):
    caplog.set_level("INFO", logger="service.calls")
    summary = "Recorded savings capacity is SGD 1600."
    issue = {"section_id": "budget", "requirement": "Private correction wording.",
             "category": "factual_qualification", "action": "qualify", "claim_quote": summary,
             **changes}
    gateway = _DecisionGateway({"blocked": True, "request_allowed": True, "complete": True,
        "missing_points": [], "financial_language_safe": True, "blocking_issues": [issue],
        "block_categories": ["factual_qualification"], "policy_notes": ["Private reviewer explanation."],
        "summary": "Private review verdict.", "rationale": ["Private reviewer rationale."], "confidence": 1})
    result = AgentResult(agent="budget", summary=summary, data={"estimated_savings_capacity": 1600})
    result._financial_grounding_snapshot = FinancialGroundingSnapshot.capture(
        AgentTask(agent="budget", sanitized_message="Explain recorded capacity."), result.data,
        prompt_content_hash=PromptCatalog().content_hash,
    )
    review = RiskComplianceAgent(gateway, PromptCatalog(), 0.1, 3000,
        LocalDocumentPolicyRetriever()).validate(
            CoachRequest(user_id="synthetic", session_id="contract", message="Explain my budget capacity."),
            [result], summary)
    assert review.blocked and len(gateway.calls) == 2
    assert review.data["validation_reason"] == reason
    assert review.data["policy_clause_refs"] == []
    assert reason in caplog.text
    assert "Private reviewer" not in caplog.text
    public = withhold_agent_result(review)
    assert public.data["validation_reason"] == reason
    assert "Private" not in public.model_dump_json()


def test_optional_education_gap_retains_financial_authority_and_scoped_review():
    class GapAgent(BaseAgent):
        name = AgentName.BUDGET
        prompt_id = "agent_budget"

        def _ground(self, task, sanitized_message):
            return {"evidence_status": "insufficient", "contexts": [], "sources": [],
                    "estimated_savings_capacity": 1600}

    gateway = _RecordingGateway()
    result = GapAgent(gateway, PromptCatalog(), 0.1, 3000).run_task(
        AgentTask(agent="budget", sanitized_message="Explain capacity and liquidity.")
    ).result
    assert result._financial_grounding_snapshot.grounding == result.data
    assert not gateway.calls
    review = RiskComplianceAgent(gateway, PromptCatalog(), 0.1, 3000,
        LocalDocumentPolicyRetriever()).validate(
            CoachRequest(user_id="synthetic", session_id="gap", message="Explain capacity and liquidity."),
            [result], result.summary)
    assert not review.blocked and review.data["request_allowed"]
    assert review.data["answer_complete"]
    payload = json.loads(gateway.calls[0]["user_prompt"])
    assert payload["agent_results"][0]["data"]["estimated_savings_capacity"] == 1600
    assert payload["agent_results"][0]["data"]["contexts"] == []
    assert "_financial_grounding_snapshot" not in result.model_dump_json()
    result.data["estimated_savings_capacity"] = 1700
    from app.models.gateway import ModelGatewayError

    with pytest.raises(ModelGatewayError, match="authority changed"):
        RiskComplianceAgent(gateway, PromptCatalog(), 0.1, 3000,
            LocalDocumentPolicyRetriever()).validate(
                CoachRequest(user_id="synthetic", session_id="changed", message="Explain capacity."),
                [result], result.summary)


def test_valid_factual_block_has_policy_reference_and_safe_public_reason():
    gateway = _DecisionGateway({"blocked": True, "summary": "Private review verdict.",
        "rationale": ["Private rationale."], "policy_notes": ["Private qualification wording."],
        "block_categories": ["factual_qualification"], "confidence": 1})
    review = RiskComplianceAgent(gateway, PromptCatalog(), 0.1, 3000,
        LocalDocumentPolicyRetriever()).validate(
            CoachRequest(user_id="synthetic", session_id="qualification", message="Explain my budget."),
            [], "A recorded amount.")
    assert review.data["policy_clause_refs"] == ["EV-03"]
    public = withhold_agent_result(review)
    assert "factual qualification" in public.summary
    assert public.data["policy_clause_refs"] == ["EV-03"]
    assert "Private" not in public.model_dump_json()
