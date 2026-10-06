"""Budget/Goal use the same public query and semantic evidence contracts."""

import json

import pytest
from test_education_semantic_coverage import (
    PLAN,
    QUOTE,
    RecordingRetriever,
    ScriptedSemanticGateway,
    coverage,
)

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


class ConditionalGateway(ScriptedSemanticGateway):
    def generate(self, **kwargs):
        component = kwargs["system_prompt"].splitlines()[0]
        if component in {"PROMPT_ID: agent_budget", "PROMPT_ID: agent_goal_strategy"}:
            self.calls.append(kwargs)
            grounding = json.loads(kwargs["user_prompt"])["grounding"]
            response = json.loads(LocalFixtureModelGateway().generate(**kwargs))
            if grounding.get("contexts"):
                response["summary"] += " " + QUOTE + " [source:etf-source]"
            return json.dumps(response)
        return super().generate(**kwargs)


def request(*, agents=("budget",), financial_inputs=True):
    return CoachRequest(
        user_id="synthetic", session_id="conditional-semantic",
        message=("Calculate my disposable income from my profile income and explain why an ETF can differ from its index."
                 if financial_inputs else "Explain a monthly budget and why an ETF can differ from its index."),
        requested_agents=list(agents),
        snapshot={
            "monthly_income": {"amount": 4000},
            "goals": [{"name": "Home deposit", "target_amount": {"amount": 1200}, "target_months": 12}],
        } if financial_inputs else {},
    )


def workflow(gateway, retriever):
    return AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="openai"), gateway=gateway, education_retriever=retriever,
    )


def semantic_calls(gateway, role):
    return [call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: " + role + "\n")]


@pytest.mark.parametrize("agents", [("budget",), ("goal_strategy",), ("budget", "goal_strategy")])
def test_conditional_consumers_get_quote_backed_coverage_once(agents):
    gateway, retriever = ConditionalGateway(), RecordingRetriever()
    response = workflow(gateway, retriever).handle(request(agents=agents))
    assert not response.blocked
    consumers = [result for result in response.agent_results if result.agent in {"budget", "goal_strategy"}]
    assert consumers
    for result in consumers:
        assert result.data["coverage_assessment"] == "model_semantic_with_exact_quotes"
        assert result.data["subquestion_coverage"][0]["supporting_passages"][0]["quote"] == QUOTE
        assert result.data["fallback_topics"] == []
        assert result.data["unanswered_topics"] == []
        assert result.data["sources"][0]["source_id"] == "etf-source"
    assert len(semantic_calls(gateway, "education_query_planner")) == 1
    assert len(semantic_calls(gateway, "education_answerability")) == 1
    assert len(retriever.queries) == len(set(retriever.queries))


def test_direct_education_owns_assessed_context_without_duplicate_model_calls():
    gateway, retriever = ConditionalGateway(), RecordingRetriever()
    response = workflow(gateway, retriever).handle(request(agents=("budget", "investment_education")))
    assert not response.blocked
    assert len(semantic_calls(gateway, "education_query_planner")) == 1
    assert len(semantic_calls(gateway, "education_answerability")) == 1
    budget = next(result for result in response.agent_results if result.agent == "budget")
    education = next(result for result in response.agent_results if result.agent == "investment_education")
    assert education.data["coverage_assessment"] == "model_semantic_with_exact_quotes"
    assert budget.data["disposable_income"] == 4000
    assert not budget.data.get("contexts") and not budget.data.get("sources")
    assert "general_knowledge" not in budget.data
    assert "because of fees and timing" in response.answer


def test_general_budget_preserves_education_without_saved_income():
    gateway, retriever = ConditionalGateway(), RecordingRetriever()
    response = workflow(gateway, retriever).handle(request(financial_inputs=False))
    assert not response.blocked
    budget = next(result for result in response.agent_results if result.agent == "budget")
    assert budget.data["calculation_status"] == "no_financial_inputs"
    assert budget.data["sources"][0]["source_id"] == "etf-source"
    assert "because of fees and timing" in response.answer
    assert "disposable_income" not in budget.data


def test_unanswerable_keyword_hits_do_not_reach_conditional_writer_as_sources():
    gateway = ConditionalGateway(support=coverage(status="unsupported"))
    retriever = RecordingRetriever("An ETF tracks an index. Fees are mentioned.")
    response = workflow(gateway, retriever).handle(request())
    assert not response.blocked
    budget = next(result for result in response.agent_results if result.agent == "budget")
    assert budget.data["evidence_status"] == "insufficient"
    assert budget.data["sources"] == [] and budget.data["contexts"] == []
    assert budget.data["disposable_income"] == 4000
    assert "because of fees and timing" not in response.answer
    assert not semantic_calls(gateway, "agent_budget")


def test_invalid_semantic_support_preserves_calculation_after_one_repair():
    gateway = ConditionalGateway(support=coverage(quote="A claim absent from the carried source."))
    response = workflow(gateway, RecordingRetriever()).handle(request())
    assert not response.blocked
    budget = next(result for result in response.agent_results if result.agent == "budget")
    assert budget.data["disposable_income"] == 4000
    assert budget.data["evidence_status"] == "insufficient"
    assert len(semantic_calls(gateway, "education_answerability")) == 2
    assert not semantic_calls(gateway, "agent_budget")


def test_unsafe_semantic_plan_cannot_reach_conditional_retrieval():
    plan = json.loads(json.dumps(PLAN))
    plan["subquestions"][0]["query_terms"] = ["my salary"]
    gateway, retriever = ConditionalGateway(plan=plan), RecordingRetriever()
    response = workflow(gateway, retriever).handle(request())
    assert not response.blocked
    assert retriever.queries == []
    budget = next(result for result in response.agent_results if result.agent == "budget")
    assert budget.data["disposable_income"] == 4000
    assert len(semantic_calls(gateway, "education_query_planner")) == 2
