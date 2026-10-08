"""Regressions for the evidence and recovery failures in the 8 October run."""

import json
from copy import deepcopy

import pytest
from test_conditional_financial_dependencies import RecordingGateway, request
from test_financial_review_repair import FinancialReviewGateway, ask

from app.agents.risk_compliance import RiskComplianceAgent
from app.core.config import Settings
from app.core.financial_grounding import FinancialGroundingSnapshot
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentResult, AgentTask, CoachRequest
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.policy import LocalPolicyRetriever


def calls_for(gateway, role):
    return [call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: " + role + "\n")]


def test_goal_reviewer_receives_the_writer_progress_and_assumptions_contract():
    gateway = RecordingGateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        request("Calculate saved goal progress and equal monthly contributions.", ["goal_strategy"]))
    assert not response.blocked
    writer = json.loads(calls_for(gateway, "agent_goal_strategy")[0]["user_prompt"])
    review = json.loads(calls_for(gateway, "risk_compliance")[0]["user_prompt"])
    data = next(item["data"] for item in review["agent_results"] if item["agent"] == "goal_strategy")
    assert data["goal_progress"] == writer["grounding"]["goal_progress"]
    assert data["projections"] == writer["grounding"]["projections"]
    assert "goal_strategy.goal_progress" in review["evidence_refs"]


def test_review_rejects_modified_financial_evidence_instead_of_trusting_result_json():
    task = AgentTask(agent="goal_strategy", sanitized_message="Show goal progress.")
    data = {"goal_progress": [{"current_amount": 600, "target_amount": 3600}],
            "calculation_assumptions": {"starting_amount": 0}}
    result = AgentResult(agent="goal_strategy", summary="Saved progress.", rationale=["Saved goal."], confidence=1, data=deepcopy(data))
    result._financial_grounding_snapshot = FinancialGroundingSnapshot.capture(task, data, prompt_content_hash="test")
    result.data["goal_progress"][0]["current_amount"] = 900
    with pytest.raises(ModelGatewayError, match="review authority changed"):
        RiskComplianceAgent(RecordingGateway(), PromptCatalog(), 0.1, 1600, LocalPolicyRetriever()).validate(
            CoachRequest(user_id="u", session_id="s", message="Show progress."), [result], result.summary)


class ClaimGateway(FinancialReviewGateway):
    def __init__(self, action, *, invalid_ref=False, invalid_range=False, unsafe=False):
        super().__init__("unverifiable_claim")
        self.action, self.invalid_ref, self.invalid_range, self.unsafe = action, invalid_ref, invalid_range, unsafe

    def generate(self, **kwargs):
        value = super().generate(**kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance") and self.rounds == 1:
            data = json.loads(value)
            payload = json.loads(kwargs["user_prompt"])
            issue = data["blocking_issues"][0]
            issue.update(action=self.action, claim_start=0, claim_end=len(payload["draft_answer"]))
            if self.action == "ground_claim":
                issue["evidence_refs"] = ["spending.fabricated" if self.invalid_ref else "spending.category_totals"]
            if self.invalid_range:
                issue["claim_end"] += 1
            if self.unsafe:
                data["block_categories"].append("personal_advice")
            return json.dumps(data)
        return value


@pytest.mark.parametrize("action", ["ground_claim", "remove_claim"])
def test_identified_financial_claim_can_be_corrected_once_from_unchanged_evidence(action):
    gateway = ClaimGateway(action)
    response = ask(gateway)
    assert not response.blocked and gateway.rounds == 2 and len(gateway.writes) == 2
    assert gateway.writes[0]["grounding"] == gateway.writes[1]["grounding"]
    correction = gateway.writes[1]["review_corrections"][0]
    assert correction["action"] == action
    assert correction["original_claim"] == gateway.writes[1]["original_summary"]
    assert "household coverage is incomplete" in response.answer


def test_unsafe_category_never_enters_claim_correction():
    gateway = ClaimGateway("remove_claim", unsafe=True)
    response = ask(gateway)
    assert response.blocked and gateway.rounds == 1 and len(gateway.writes) == 1
    decision = next(event for event in response.audit["events"] if event["event_type"] == "financial.review.repair_decision")
    assert "REPAIR_VERDICT_NOT_REPAIRABLE" in decision["details"]["repair_blockers"]


class MixedGateway(FinancialReviewGateway):
    def __init__(self, *, both=False):
        super().__init__()
        self.calls, self.both = [], both

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            return json.dumps({"selected_agents": ["spending", "investment_education"],
                "rationale": ["Two independent requested analyses."],
                "education_topics": ["diversification"], "education_search_terms": ["diversification"],
                "task_assignments": [
                    {"agent": "spending", "question": "Analyze recorded October spending.",
                     "source_quotes": ["Analyze recorded October spending"]},
                    {"agent": "investment_education", "question": "Explain diversification.",
                     "source_quotes": ["explain diversification"], "education_topics": ["diversification"]}]})
        value = super().generate(**kwargs)
        if self.both and kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance") and self.rounds == 1:
            data = json.loads(value)
            data["blocking_issues"].append({"section_id": "investment_education",
                "requirement": "Preserve the source's limitation that diversification cannot eliminate losses."})
            return json.dumps(data)
        return value


@pytest.mark.parametrize("both", [False, True])
def test_mixed_spending_education_repairs_only_affected_owners_and_preserves_sections(both):
    gateway = MixedGateway(both=both)
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u", session_id="s",
            message="Analyze recorded October spending; independently explain diversification.",
            snapshot={"period_start": "2026-10-01", "recent_transactions": [
                {"description": "Food", "category": "food", "amount": {"amount": 50}, "occurred_on": "2026-10-02"}]}))
    assert not response.blocked and gateway.rounds == 2 and len(gateway.writes) == 2
    assert len(calls_for(gateway, "agent_investment_education")) == (2 if both else 1)
    assert not calls_for(gateway, "synthesizer")
    assert response.audit["dependency_edges"] == []
    for result in response.agent_results[:-1]:
        assert result.summary in response.answer
    initial = json.loads(calls_for(gateway, "risk_compliance")[0]["user_prompt"])
    assert {section["agent"] for section in initial["review_sections"]} >= {"spending", "investment_education"}


def test_financial_claim_and_education_qualification_receive_distinct_owned_corrections():
    class MixedClaimGateway(MixedGateway):
        def generate(self, **kwargs):
            value = super().generate(**kwargs)
            if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance") and self.rounds == 1:
                verdict = json.loads(value)
                payload = json.loads(kwargs["user_prompt"])
                section = next(s for s in payload["review_sections"] if s["section_id"] == "spending")
                verdict["block_categories"].append("unverifiable_claim")
                verdict["blocking_issues"][0].update(category="unverifiable_claim", action="ground_claim",
                    claim_start=section["start"], claim_end=section["end"], evidence_refs=["spending.category_totals"])
                verdict["blocking_issues"][1]["category"] = "factual_qualification"
                return json.dumps(verdict)
            return value
    gateway = MixedClaimGateway(both=True)
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u", session_id="s",
            message="Analyze recorded October spending; independently explain diversification.",
            snapshot={"period_start": "2026-10-01", "recent_transactions": [
                {"description": "Food", "category": "food", "amount": {"amount": 50}, "occurred_on": "2026-10-02"}]}))
    assert not response.blocked and gateway.rounds == 2
    assert len(gateway.writes) == len(calls_for(gateway, "agent_investment_education")) == 2
    assert not calls_for(gateway, "synthesizer")


class CaptureFallbackGateway(FinancialReviewGateway):
    def __init__(self):
        super().__init__()
        self.extracts = 0

    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            return json.dumps({"selected_agents": ["spending"], "spending_capture": True,
                               "rationale": ["Candidate spending operation."]})
        if kwargs["system_prompt"].startswith("PROMPT_ID: spending_capture"):
            self.extracts += 1
            return json.dumps({"is_spending_request": False})
        return super().generate(**kwargs)


def test_capture_fallback_clears_workflow_state_before_grounding_and_repair():
    gateway = CaptureFallbackGateway()
    response = ask(gateway)
    assert not response.blocked and gateway.extracts == 1 and gateway.rounds == 2
    assert response.audit["turn_decision"]["spending_capture"] is False
    assert len(gateway.writes) == 2
    assert not any("spending_draft" in result.data for result in response.agent_results)
    decision = next(event for event in response.audit["events"] if event["event_type"] == "financial.review.repair_decision")
    assert decision["details"]["allowed"] and "REPAIR_CAPTURE_WORKFLOW" not in decision["details"]["repair_blockers"]


@pytest.mark.parametrize("error", ["foreign_ref", "unknown_ref", "outside_section", "missing_ref"])
def test_invalid_claim_authority_never_grants_repair(error):
    data = {"savings": 700}
    task = AgentTask(agent="budget", sanitized_message="Explain saved capacity.")
    result = AgentResult(agent="budget", summary="Saved capacity is SGD 700.", rationale=["Saved plan."], confidence=1, data=data)
    result._financial_grounding_snapshot = FinancialGroundingSnapshot.capture(task, data, prompt_content_hash="test")
    issue = {"section_id": "budget", "requirement": "Use the saved allocation.", "action": "ground_claim",
             "claim_start": 0, "claim_end": len(result.summary), "evidence_refs": ["budget.savings"]}
    if error == "foreign_ref":
        issue["evidence_refs"] = ["goal_strategy.projections"]
    if error == "unknown_ref":
        issue["evidence_refs"] = ["budget.fabricated"]
    if error == "outside_section":
        issue["claim_end"] += 1
    if error == "missing_ref":
        issue["evidence_refs"] = []
    verdict = {"blocked": True, "request_allowed": True, "complete": True, "missing_points": [],
               "financial_language_safe": True, "blocking_issues": [issue], "block_categories": ["unverifiable_claim"],
               "policy_notes": ["Use verified evidence."], "summary": "Claim correction required.",
               "rationale": ["The draft has an unsupported claim."], "confidence": 1}
    class InvalidGateway:
        def generate(self, **kwargs):
            return json.dumps(verdict)
    review = RiskComplianceAgent(InvalidGateway(), PromptCatalog(), 0.1, 1600, LocalPolicyRetriever()).validate(
        CoachRequest(user_id="u", session_id="s", message="Explain saved capacity."), [result], result.summary)
    assert review.blocked and not review.data.get("repairable")


def test_emergency_explanation_does_not_override_semantic_goal_routing():
    message = "Explain emergency-fund readiness and what my recorded expenses imply about building a reserve."
    class GoalOnlyGateway(RecordingGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
                self.calls.append(kwargs)
                return json.dumps({"selected_agents": ["goal_strategy"], "rationale": ["Assess reserve readiness."],
                    "spending_capture": False, "education_topics": ["emergency fund readiness"],
                    "task_assignments": [{"agent": "goal_strategy", "question": message,
                        "source_quotes": [message], "requires_capacity": False,
                        "education_topics": ["emergency fund readiness"]}]})
            return super().generate(**kwargs)
    gateway = GoalOnlyGateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        request(message, ["goal_strategy"]))
    assert not response.blocked and [agent.value for agent in response.selected_agents] == ["goal_strategy"]
    assert not calls_for(gateway, "spending_capture") and not calls_for(gateway, "agent_spending")
    routing = next(event for event in response.audit["events"] if event["event_type"] == "routing.completed")
    assert not routing["details"]["after"]["spending_capture"]


def test_composition_correction_receives_original_draft_and_verified_financial_facts():
    class CompositionGateway(RecordingGateway):
        def __init__(self):
            super().__init__()
            self.reviews = 0
        def generate(self, **kwargs):
            role = kwargs["system_prompt"].splitlines()[0]
            payload = json.loads(kwargs["user_prompt"])
            if role == "PROMPT_ID: synthesizer":
                self.calls.append(kwargs)
                if "review_corrections" not in payload:
                    return json.dumps({"answer": "The entire household spent SGD 660."})
                return json.dumps({"answer": "Recorded food spending is SGD 660; household coverage is incomplete. Saved savings capacity is SGD 700."})
            if role == "PROMPT_ID: risk_compliance":
                self.reviews += 1
                if self.reviews == 1:
                    self.calls.append(kwargs)
                    return json.dumps({"blocked": True, "request_allowed": True, "complete": True,
                        "missing_points": [], "financial_language_safe": True,
                        "blocking_issues": [{"section_id": "draft", "requirement": "Qualify recorded coverage without inferring household completeness.",
                                             "claim_quote": payload["draft_answer"]}],
                        "block_categories": ["factual_qualification"], "policy_notes": ["The aggregate needs qualification."],
                        "summary": "Correction required.", "rationale": ["Incomplete record coverage."], "confidence": 1})
            return super().generate(**kwargs)
    gateway = CompositionGateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        request("Analyze spending independently of my saved budget capacity.", ["spending", "budget"], capacity=True))
    assert not response.blocked and gateway.reviews == 2
    assert len(calls_for(gateway, "agent_spending")) == len(calls_for(gateway, "agent_budget")) == 1
    composition = calls_for(gateway, "synthesizer")
    assert len(composition) == 2
    correction = json.loads(composition[1]["user_prompt"])
    assert correction["original_draft"] == "The entire household spent SGD 660."
    assert correction["review_corrections"][0]["section_id"] == "draft"
    facts = {item["agent"]: item["data"] for item in correction["verified_grounding"]}
    assert facts["spending"]["category_totals"] == {"food": 660}
    assert facts["budget"]["capacity"]["estimated_savings_capacity"] == 700
