"""Review the paragraph-label and repair-verdict failures found in Edge testing."""

import json

import pytest
from coach_i18n import translate
from test_goal_education_recovery import GoalEducationGateway, ask

from app.agents.investment_education import InvestmentEducationAgent
from app.agents.risk_compliance import RiskComplianceAgent
from app.core.config import Settings
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentResult,
    CoachRequest,
    HybridEducationNarrative,
    ScopedEducationComplianceDecision,
)
from app.models.contracts import output_format, structured_contract
from app.models.gateway import LocalFixtureModelGateway, ModelGeneration
from app.rag.policy import LocalPolicyRetriever
from app.rag.retriever import LocalEducationRetriever

MODEL_TEXT = [
    {"topic": "diversification", "text": "Different investments can fall together."},
    {"topic": "investment time horizon", "text": "With less time, there is less time to recover from a loss."},
]


def formatted(locale="en", lead="sourced"):
    agent = InvestmentEducationAgent(LocalFixtureModelGateway(), PromptCatalog(),
                                    0.2, 4000, LocalEducationRetriever())
    data = {"response_language": locale, "general_knowledge": MODEL_TEXT,
            "fallback_topics": [item["topic"] for item in MODEL_TEXT]}
    narrative = HybridEducationNarrative(summary="Diversification spreads exposure.",
        rationale=["Concept explanation."], confidence=0.9, general_knowledge=MODEL_TEXT,
        lead_section=lead)
    summary = agent._format_summary(narrative, data)
    return AgentResult(agent=AgentName.INVESTMENT_EDUCATION, summary=summary,
                       rationale=["Concept explanation."], confidence=0.9, data=data)


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize("lead", ["sourced", "model"])
def test_each_model_topic_has_a_visible_label_and_exact_review_range(locale, lead):
    result = formatted(locale, lead)
    label = translate("education.model_knowledge_label", locale)
    assert result.summary.count(label) == 2
    for item in MODEL_TEXT:
        section = next(section for section in result.data["review_sections"] if section.get("topic") == item["topic"])
        assert section["provenance"] == "model_knowledge"
        assert result.summary[section["start"]:section["end"]] == label + "\n" + item["text"]


def verdict(section="education_3", *, categories=None, allowed=True, safe=True):
    return {"blocked": True, "request_allowed": allowed, "complete": True,
            "missing_points": [], "financial_language_safe": safe,
            "blocking_issues": [{"section_id": section, "requirement": "Preserve the time-horizon qualification and label."}],
            "block_categories": categories or ["factual_qualification"],
            "summary": "The draft requires correction.", "rationale": ["The identified section needs qualification."],
            "policy_notes": ["The specified section needs correction."], "confidence": 0.9}


class ReviewGateway:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(next(self.decisions))


def review(decisions):
    gateway = ReviewGateway(decisions)
    agent = RiskComplianceAgent(gateway, PromptCatalog(), 0.1, 3000, LocalPolicyRetriever())
    education = formatted()
    budget = AgentResult(agent=AgentName.BUDGET, summary="The confirmed plan assigns SGD 1,000 to savings.",
                         rationale=["Saved plan."], confidence=0.9)
    request = CoachRequest(user_id="synthetic", session_id="review", message="Assess my budget and explain investment time horizon.")
    draft = budget.summary + "\n\n" + education.summary
    return agent.validate(request, [budget, education], draft), gateway


def test_complete_education_qualification_defect_derives_repair_without_a_model_boolean():
    result, gateway = review([verdict()])
    assert result.blocked and result.data["answer_complete"]
    assert result.data["repairable"]
    assert result.data["missing_points"] == ["Preserve the time-horizon qualification and label."]
    payload = json.loads(gateway.calls[0]["user_prompt"])
    section = next(section for section in payload["review_sections"] if section["section_id"] == "education_3")
    assert section["agent"] == "investment_education" and section["provenance"] == "model_knowledge"
    assert payload["draft_answer"][section["start"]:section["end"]].endswith(MODEL_TEXT[1]["text"])
    assert "Do not return repairable" in gateway.calls[0]["system_prompt"]
    assert "repairable (boolean)" not in gateway.calls[0]["system_prompt"]
    with structured_contract(ScopedEducationComplianceDecision):
        contract = output_format()
        assert contract["strict"] and "repairable" not in contract["schema"]["properties"]


@pytest.mark.parametrize("options", [
    {"section": "budget"}, {"section": "draft"},
    {"section": "request", "categories": ["prohibited_request"], "allowed": False},
    {"categories": ["return_guarantee"]},
])
def test_financial_unowned_prohibited_or_unsafe_issues_never_admit_education_repair(options):
    result, _ = review([verdict(**options)])
    assert result.blocked and not result.data["repairable"]


def test_qualification_can_enter_correction_while_the_original_draft_remains_unsafe():
    result, _ = review([verdict(safe=False)])
    assert result.blocked and result.data["repairable"]


def test_mixed_financial_and_education_defects_cannot_be_reassigned_to_education():
    decision = verdict()
    decision["blocking_issues"].append({"section_id": "budget", "requirement": "Preserve the saved capacity source."})
    result, _ = review([decision])
    assert result.blocked and not result.data["repairable"]


@pytest.mark.parametrize("section,repairable", [("education_3", True), ("budget", False)])
def test_safe_incomplete_review_also_requires_education_ownership(section, repairable):
    decision = verdict(section=section)
    decision.update(blocked=False, complete=False, block_categories=[], policy_notes=[],
                    missing_points=[decision["blocking_issues"][0]["requirement"]])
    result, _ = review([decision])
    assert not result.blocked and not result.data["answer_complete"]
    assert result.data["repairable"] is repairable


def test_unknown_section_gets_one_contract_correction_with_the_same_draft():
    result, gateway = review([verdict(section="invented"), verdict()])
    assert len(gateway.calls) == 2 and result.data["repairable"]
    before, after = [json.loads(call["user_prompt"]) for call in gateway.calls]
    assert before["draft_answer"] == after["draft_answer"]
    assert before["review_sections"] == after["review_sections"]
    assert "education_3" in after["correction_feedback"]["validation_issues"]
    assert "invented" not in after["correction_feedback"]["validation_issues"]


def test_exhausted_unknown_section_withholds_review_and_does_not_admit_correction():
    result, gateway = review([verdict(section="invented")] * 2)
    assert len(gateway.calls) == 2 and result.blocked
    assert result.data["block_reasons"] == ["review_contract_unverified"]
    assert not result.data.get("repairable")


class ScopedGoalGateway(GoalEducationGateway):
    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance"):
            self.calls.append(kwargs)
            self.reviews += 1
            if self.reviews == 1:
                value = verdict(section="investment_education")
            else:
                value = verdict()
                value.update(blocked=False, blocking_issues=[], block_categories=[], policy_notes=[])
            return ModelGeneration(json.dumps(value), usage={"inputTokens": 6900, "outputTokens": 400, "totalTokens": 7300})
        return super().generate(**kwargs)


class IncompleteGoalGateway(ScopedGoalGateway):
    def __init__(self, section):
        super().__init__()
        self.section = section

    def generate(self, **kwargs):
        generation = super().generate(**kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance") and self.reviews == 1:
            decision = verdict(section=self.section)
            decision.update(blocked=False, complete=False, block_categories=[], policy_notes=[],
                            missing_points=[decision["blocking_issues"][0]["requirement"]])
            return ModelGeneration(json.dumps(decision), usage=generation.usage)
        return generation


@pytest.mark.parametrize("section,corrections", [("investment_education", 1), ("budget", 0)])
def test_incomplete_combined_answer_repairs_only_its_owned_specialist(section, corrections):
    gateway = IncompleteGoalGateway(section)
    response = ask(gateway, MAX_MODEL_TOKENS_PER_RUN=80000)
    assert not response.blocked
    assert gateway.writers == 1 + corrections and gateway.reviews == 2
    assert len(gateway.calls_for("agent_budget")) == 2 - corrections
    assert len(gateway.calls_for("agent_goal_strategy")) == 1
    for result in response.agent_results:
        if result.agent in {AgentName.BUDGET, AgentName.GOAL_STRATEGY}:
            assert result.summary in response.answer


def test_combined_current_correction_keeps_financial_text_and_uses_one_independent_rereview():
    gateway = ScopedGoalGateway()
    response = ask(gateway, MAX_MODEL_TOKENS_PER_RUN=80000)
    assert not response.blocked and gateway.writers == gateway.reviews == 2
    for role in ("agent_budget", "agent_goal_strategy", "education_query_planner", "education_answerability"):
        assert len(gateway.calls_for(role)) == 1
    for result in response.agent_results:
        if result.agent in {AgentName.BUDGET, AgentName.GOAL_STRATEGY}:
            assert result.summary in response.answer
    assert not gateway.calls_for("synthesizer") and not gateway.calls_for("budget_capture")
    assert response.audit["model_calls"][-1]["component"] == "risk_compliance"


def test_application_default_is_80000_and_explicit_smaller_limit_is_preserved():
    assert Settings(_env_file=None).max_model_tokens_per_run == 80000
    assert Settings(_env_file=None, MAX_MODEL_TOKENS_PER_RUN=10000).max_model_tokens_per_run == 10000


def test_configuration_cannot_select_a_retired_prompt_set():
    with pytest.raises(ValueError, match="requires PROMPT_SET_VERSION="):
        Settings(_env_file=None, PROMPT_SET_VERSION="retired-release")


def test_active_app_defaults_include_all_recommended_role_policies():
    settings = Settings(_env_file=None)
    assert settings.model_reasoning_effort == "medium"
    assert settings.model_max_tokens == 3200
    for role in ("agent_budget", "agent_goal_strategy", "agent_spending"):
        policy = settings.model_policy(role, 1600)
        assert policy.reasoning_effort == "medium" and policy.max_tokens == 3200
    education = settings.model_policy("agent_investment_education", 1600)
    review = settings.model_policy("risk_compliance", 1600)
    assert (education.reasoning_effort, education.max_tokens) == ("medium", 4000)
    assert (review.reasoning_effort, review.max_tokens) == ("medium", 3000)
    router = settings.model_policy("router", settings.model_max_tokens)
    assert (router.reasoning_effort, router.max_tokens) == ("low", 1800)
