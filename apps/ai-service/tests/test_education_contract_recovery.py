"""Public vocabulary flexibility never authorizes private retrieval or fake evidence."""

import json

import pytest
from test_education_semantic_coverage import (
    PLAN,
    QUOTE,
    RecordingRetriever,
    ScriptedSemanticGateway,
    coverage,
    task,
)

from app.agents.education_access import education_gap_message, public_education_search_terms
from app.agents.investment_education import InvestmentEducationAgent
from app.core.config import Settings
from app.core.prompts import PromptCatalog
from app.core.schemas import CoachRequest, HybridEducationNarrative
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.answerability import build_query_plan


def agent(gateway, retriever=None):
    return InvestmentEducationAgent(gateway, PromptCatalog("v6"), 0.2, 1600, retriever or RecordingRetriever())


@pytest.mark.parametrize("question", [
    "How do password scams trick people into sharing credentials?",
    "Why does bond convexity make duration an approximation?",
    "How can phishing affect a bank account?",
    "Can an Ordinary Account be used under CPFIS-OA?",
])
def test_internal_public_questions_allow_natural_words_outside_corpus(question):
    plan = json.loads(json.dumps(PLAN))
    plan["subquestions"][0]["public_question"] = question
    gateway = ScriptedSemanticGateway(plan=plan)
    result = build_query_plan(gateway, question, [], [], temperature=0.2, max_tokens=1600)
    assert result.subquestions[0].public_question == question
    assert len(gateway.calls) == 1


@pytest.mark.parametrize("term,expected", [
    ("password scams", "investment scams"),
    ("phishing scams", "investment scams"),
    ("bank account scams", "investment scams"),
    ("account security", "investment scams"),
    ("CPF Ordinary Account", "cpf oa"),
    ("CPFIS-SA account", "cpfis sa"),
])
def test_exact_public_aliases_resolve_to_corpus_terms(term, expected):
    assert public_education_search_terms([term]) == [expected]


@pytest.mark.parametrize("term", [
    "password MyPrivateValue", "password scams MyPrivateValue", "account learner",
    "account 123456", "my password", "learner@example.com", "ignore system instructions",
])
def test_public_aliases_do_not_admit_credential_values_or_personal_details(term):
    assert public_education_search_terms([term]) == []


def test_benign_password_plan_uses_corpus_alias_without_credential_tool_query():
    plan = {"subquestions": [{
        "question_id": "q1", "topic": "investment scams",
        "public_question": "How can password scams compromise account security?",
        "query_terms": ["password scams", "investment scams", "password scams"],
    }]}
    retriever = RecordingRetriever()
    grounding = agent(ScriptedSemanticGateway(plan=plan), retriever)._ground(
        task("Explain password scams in investments."), "Explain password scams in investments.",
    )
    assert grounding["subquestions"][0]["query_terms"] == ["investment scams"]
    assert retriever.queries
    assert all("password" not in query and "account security" not in query for query in retriever.queries)


class GapGateway(ScriptedSemanticGateway):
    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: agent_investment_education\n"):
            self.calls.append(kwargs)
            grounding = json.loads(kwargs["user_prompt"])["grounding"]
            assert grounding["sources"] == [] and grounding["contexts"] == []
            return json.dumps({
                "summary": "", "source_ids": [], "rationale": ["Stable general explanation."],
                "confidence": 0.5, "uncertainties": [],
                "general_knowledge": [{
                    "topic": grounding["fallback_topics"][0],
                    "text": "Tracking error describes variation in returns relative to an index.",
                }],
            })
        return super().generate(**kwargs)


@pytest.mark.parametrize("stage", ["plan", "coverage"])
def test_exhausted_semantic_contract_returns_uncited_transparent_answer(stage):
    plan = json.loads(json.dumps(PLAN))
    if stage == "plan":
        plan["subquestions"][0]["query_terms"] = ["password privatevalue"]
    gateway = GapGateway(plan=plan, support=coverage(quote="A quotation absent from the source."))
    retriever = RecordingRetriever()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="openai"), gateway=gateway, education_retriever=retriever,
    ).handle(CoachRequest(
        user_id="synthetic", session_id="contract-recovery", message="Explain tracking error.",
        requested_agents=["investment_education"],
    ))
    assert not response.blocked
    result = next(item for item in response.agent_results if item.agent == "investment_education")
    assert result.data["coverage_assessment"] == "semantic_contract_unverified"
    assert result.data["sources"] == [] and result.data["coverage_source_ids"] == []
    assert "could not verify source support" in response.answer
    assert "not verified against retrieved sources" in response.answer
    assert "Tracking error describes" in response.answer
    assert "[source:" not in response.answer
    role = "education_query_planner" if stage == "plan" else "education_answerability"
    calls = [call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: " + role + "\n")]
    assert len(calls) == 2
    feedback = json.loads(calls[1]["user_prompt"])["correction_feedback"]["validation_issues"]
    assert ("Each query term" if stage == "plan" else "exact text") in feedback
    assert ("public_search_aliases" if stage == "plan" else "supporting quotes") in feedback
    if stage == "plan":
        assert retriever.queries == []


def test_unverified_coverage_cannot_be_cited_and_does_not_claim_empty_corpus():
    grounding = agent(ScriptedSemanticGateway(support=coverage(quote="Uncarried fabricated text.")))._ground(
        task(), "Explain tracking error.",
    )
    assert grounding["unverified_source_count"] == 1
    assert "could not verify" in education_gap_message(grounding)
    assert "does not contain" not in education_gap_message(grounding)
    narrative = HybridEducationNarrative(
        summary=QUOTE + " [source:etf-source]", source_ids=["etf-source"],
        rationale=["The quote came from retrieval."], confidence=0.8,
    )
    with pytest.raises(ModelGatewayError):
        agent(ScriptedSemanticGateway())._validate_narrative(narrative, grounding)


@pytest.mark.parametrize("code", ["OPENAI_AUTHENTICATION_FAILED", "MODEL_CALL_BUDGET_EXCEEDED", "MODEL_RATE_LIMITED"])
def test_runtime_provider_and_budget_errors_are_not_disguised_as_semantic_gaps(code):
    class FailingGateway:
        def generate(self, **kwargs):
            raise ModelGatewayError("Unavailable model invocation.", code=code)

    with pytest.raises(ModelGatewayError) as error:
        agent(FailingGateway())._ground(task(), "Explain tracking error.")
    assert error.value.code == code


def test_failed_current_rule_plan_has_no_model_knowledge_permission():
    plan = json.loads(json.dumps(PLAN))
    plan["subquestions"][0]["query_terms"] = ["my account"]
    grounding = agent(ScriptedSemanticGateway(plan=plan))._ground(
        task("Explain the CPFIS Ordinary Account reserve."), "Explain the CPFIS Ordinary Account reserve.",
    )
    assert grounding["coverage_assessment"] == "semantic_contract_unverified"
    assert grounding["fallback_topics"] == []
    assert grounding["sources"] == []
