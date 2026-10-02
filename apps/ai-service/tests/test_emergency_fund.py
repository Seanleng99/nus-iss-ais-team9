import json

import pytest
from language_fixtures import language_case

from app.agents.education_access import build_minimal_education_query
from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
from app.rag.local_documents import LocalDocumentEducationRetriever


class EmergencyGateway(LocalFixtureModelGateway):
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["system_prompt"]
        if prompt.startswith("PROMPT_ID: router"):
            return json.dumps({"selected_agents": ["goal_strategy"], "rationale": ["Assess the reserve."],
                               "education_topics": ["emergency fund readiness"]})
        if prompt.startswith("PROMPT_ID: agent_goal_strategy"):
            return json.dumps({
                "summary": "MoneySense describes a general 3–6 months of expenses benchmark. "
                           "[source:moneysense-managing-money] "
                           "What are your complete monthly expenses? Logged rows may be incomplete.",
                "rationale": ["The expense total needs confirmation."], "confidence": 0.9,
            })
        return super().generate(**kwargs)


def workflow(gateway):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway,
                             education_retriever=LocalDocumentEducationRetriever())


@pytest.mark.parametrize(
    "message",
    [
        "use my spending to access my emergency fund goal",
        "how much should i left for emergency fund",
        language_case(
            "emergency_fund.test_emergency_questions_retrieve_guidance_without_income_or_saved_goal"
        ),
    ],
)
def test_emergency_questions_retrieve_guidance_without_income_or_saved_goal(message):
    query, topics = build_minimal_education_query(message)
    assert topics == ["emergency fund readiness"]
    assert query == "General investment education about emergency fund readiness"
    gateway = EmergencyGateway()
    result = workflow(gateway).handle(CoachRequest(user_id="synthetic", session_id="reserve", message=message))
    assert not result.blocked
    assert result.selected_agents == ["goal_strategy"]
    goal = result.agent_results[0]
    assert not goal.data.get("needs_input")
    assert "moneysense-managing-money" in {source["source_id"] for source in goal.data["sources"]}
    assert "https://www.moneysense.gov.sg/managing-your-money/" in result.answer
    review = next(json.loads(call["user_prompt"]) for call in gateway.calls
                  if call["system_prompt"].startswith("PROMPT_ID: risk_compliance"))
    assert review["agent_results"][0]["data"]["emergency_fund"]["expense_coverage"] == "unconfirmed"


def test_goal_uses_dated_spending_once_and_keeps_currencies_and_saved_balances_separate():
    rent = {"description": "Rent", "category": "housing", "amount": {"amount": 1500},
            "occurred_on": "2026-08-01"}
    snapshot = {
        "recurring_expenses": [rent],
        "recent_transactions": [rent,
            {"description": "Food", "category": "food", "amount": {"amount": 200}, "occurred_on": "2026-08-15"},
            {"description": "USD cost", "category": "food", "amount": {"amount": 30, "currency": "USD"}, "occurred_on": "2026-08-15"},
            {"description": "Partial month", "category": "food", "amount": {"amount": 100}, "occurred_on": "2026-09-01"},
            {"description": "Invalid date", "category": "food", "amount": {"amount": 999}, "occurred_on": "invalid"}],
        "goals": [{"name": "Emergency fund", "target_amount": {"amount": 12000},
                   "current_amount": {"amount": 3000}, "target_months": 12},
                  {"name": "Unclear currency", "target_amount": {"amount": 5000},
                   "current_amount": {"amount": 1000, "currency": "USD"}, "target_months": 12}],
    }
    gateway = EmergencyGateway()
    response = workflow(gateway).handle(CoachRequest(
        user_id="synthetic", session_id="saved", message="use my spending to access my emergency fund goal",
        snapshot=snapshot))
    assert not response.blocked
    goal = response.agent_results[0].data
    assert len(goal["projections"]) == 1  # No cross-currency subtraction.
    assert goal["projections"][0]["monthly_required"] == 750
    assert "monthly_savings_capacity" not in goal
    assert goal["emergency_fund"]["monthly_logged_spending"] == [
        {"month": "2026-08", "currency": "SGD", "amount": 1700},
        {"month": "2026-08", "currency": "USD", "amount": 30},
        {"month": "2026-09", "currency": "SGD", "amount": 100},
    ]
    assert goal["emergency_fund"]["invalid_transaction_dates"] == 1
    assert goal["emergency_fund"]["saved_goals"][0]["current_amount"]["amount"] == 3000
    assert all("Rent" not in call["user_prompt"] for call in gateway.calls)


def test_unavailable_sources_do_not_invent_an_emergency_benchmark():
    class EmptyRetriever:
        expected_corpus_version = "investment-education-sg@empty"

        def retrieve(self, query, top_k=3):
            return []

    result = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"), gateway=EmergencyGateway(),
        education_retriever=EmptyRetriever(),
    ).handle(CoachRequest(user_id="synthetic", session_id="gap",
                          message="how much should i left for emergency fund"))
    assert "couldn't verify the general emergency-fund guidance" in result.answer
    assert not result.sources
    assert "three to six" not in result.answer
    assert "narrower investment" not in result.answer


def test_emergency_topic_does_not_allow_account_execution():
    result = workflow(EmergencyGateway()).handle(CoachRequest(
        user_id="synthetic", session_id="blocked",
        message="Use my emergency fund to buy an ETF for me in my brokerage account."))
    assert result.blocked and not result.sources
