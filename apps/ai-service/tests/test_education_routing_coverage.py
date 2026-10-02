"""Regression coverage for real Chinese requests reaching governed Education."""
import json

import pytest
from language_fixtures import language_case

from app.core.config import Settings
from app.core.schemas import AgentName, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
from app.rag.policy import LocalPolicyRetriever
from app.rag.retriever import LocalEducationRetriever


class RouterGateway(LocalFixtureModelGateway):
    def __init__(self, selected):
        self.selected = selected
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: router\n"):
            return json.dumps({"selected_agents": self.selected, "rationale": ["Model-selected scope."]})
        return super().generate(**kwargs)


def orchestrator(gateway):
    return AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture", RAG_PROVIDER="local_fixture",
                        POLICY_RAG_PROVIDER="local_fixture", PROMPT_SET_VERSION="v6"),
        gateway=gateway, education_retriever=LocalEducationRetriever(),
        policy_retriever=LocalPolicyRetriever(),
    )


@pytest.mark.parametrize(
    "message",
    [
        language_case(
            "education_routing_coverage.test_education_topic_cannot_be_routed_only_to_spending"
        ),
        "Explain diversification and review my spending.",
    ],
)
def test_education_topic_cannot_be_routed_only_to_spending(message):
    gateway = RouterGateway(["spending"])
    response = orchestrator(gateway).handle(CoachRequest(
        user_id="synthetic-routing", session_id="synthetic-routing", message=message,
    ))
    assert AgentName.SPENDING in response.selected_agents
    assert AgentName.INVESTMENT_EDUCATION in response.selected_agents
    assert response.sources
    assert "investment_education" in response.audit["retrieval_consumers"]
    assert not response.blocked
    router = next(c for c in gateway.calls if c["system_prompt"].startswith("PROMPT_ID: router\n"))
    assert message in router["user_prompt"]


def test_explicit_budget_only_selection_remains_authoritative():
    gateway = RouterGateway(["spending"])
    response = orchestrator(gateway).handle(CoachRequest(
        user_id="synthetic-routing", session_id="synthetic-routing",
        message="Explain diversification using only my requested budget specialist.",
        requested_agents=[AgentName.BUDGET],
        snapshot={"monthly_income": {"amount": 4000, "currency": "SGD"}},
    ))
    assert response.selected_agents == [AgentName.BUDGET]
    assert not any(c["system_prompt"].startswith("PROMPT_ID: router\n") for c in gateway.calls)


def test_v6_single_education_answer_is_not_rewritten_but_is_reviewed():
    gateway = RouterGateway(["investment_education"])
    response = orchestrator(gateway).handle(CoachRequest(
        user_id="synthetic-routing", session_id="synthetic-routing",
        message="Explain diversification.", requested_agents=[AgentName.INVESTMENT_EDUCATION],
    ))
    education = next(r for r in response.agent_results if r.agent==AgentName.INVESTMENT_EDUCATION)
    assert response.answer == education.summary
    assert not any(c["system_prompt"].startswith("PROMPT_ID: synthesizer\n") for c in gateway.calls)
    assert any(c["system_prompt"].startswith("PROMPT_ID: risk_compliance\n") for c in gateway.calls)
    assert response.sources and not response.blocked


@pytest.mark.parametrize("message", [
    "Which stock should I buy?",
    "I have a credit card balance; what should I consider before investing?",
    "What tax rules apply to my investment?",
    "Can you explain compound interest?",
    "What is an index fund?",
    "What is dollar-cost averaging?",
    "What reliable sources can I use to check your explanation, and how up to date are they?",
])
def test_local_fixture_routes_canonical_investment_topics(message):
    result = LocalFixtureModelGateway._route({"message": message})
    assert "investment_education" in result["selected_agents"]


def test_local_fixture_does_not_route_unrelated_unrecognized_topic_to_education():
    result = LocalFixtureModelGateway._route({"message": "Explain the history of ancient pottery."})
    assert "investment_education" not in result["selected_agents"]


def test_local_fixture_does_not_emit_semantic_topic_field():
    result = LocalFixtureModelGateway._route({"message": "Explain compound interest."})
    assert "education_topics" not in result
    assert result["selected_agents"] == ["investment_education"]
