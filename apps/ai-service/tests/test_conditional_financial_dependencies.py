"""Saved arithmetic stays independent; funding assessments retain typed providers."""

import json
from threading import Barrier

import pytest

from app.capabilities.registry import CapabilityRegistry, CapabilityRegistryError
from app.core.config import Settings
from app.core.schemas import AgentName, CapabilityName, CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator

GOALS = [
    {"name": "Laptop", "target_amount": {"amount": 3600},
     "current_amount": {"amount": 600}, "target_months": 6},
    {"name": "Course", "target_amount": {"amount": 4800},
     "current_amount": {"amount": 800}, "target_months": 8},
]
CAPACITY = {"source": "confirmed_plan", "period_start": "2026-10-01", "currency": "SGD",
            "take_home_income": 6500, "planned_expenses": 3950,
            "estimated_savings_capacity": 700, "unallocated_income": 1850,
            "calculation_method": "Confirmed monthly savings allocation", "budget_method": "flexible"}


class RecordingGateway(LocalFixtureModelGateway):
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return super().generate(**kwargs)


def request(message, agents, *, income=False, capacity=False):
    return CoachRequest(user_id="u", session_id="conditional", message=message,
                        requested_agents=agents,
                        saved_budget_capacity=CAPACITY if capacity else {},
                        snapshot={"period_start": "2026-10-01", "goals": GOALS,
                                  **({"monthly_income": {"amount": 6500}} if income else {}),
                                  "recent_transactions": [{"description": "Recorded grocery purchase",
                                      "category": "food", "amount": {"amount": 660},
                                      "occurred_on": "2026-10-02"}]})


def run(req, gateway=None):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture", ),
                             gateway=gateway).handle(req)


@pytest.mark.parametrize("message", [
    "Calculate the remaining amount and equal monthly contribution for each saved goal.",
    "What percentage progress have I made on each saved goal?",
    "Explain the monthly savings required for my goals using their balances and durations.",
])
def test_saved_goal_arithmetic_requires_neither_budget_nor_income(message):
    gateway = RecordingGateway()
    response = run(request(message, ["goal_strategy"]), gateway)
    assert not response.blocked
    assert response.selected_agents == [AgentName.GOAL_STRATEGY]
    assert response.audit["dependency_edges"] == []
    goal = response.agent_results[0]
    assert goal.data["calculation_scope"] == "saved_goal_arithmetic"
    assert [row["remaining"] for row in goal.data["projections"]] == [3000, 4000]
    assert [row["monthly_required"] for row in goal.data["projections"]] == [500, 500]
    assert [row["progress_percent"] for row in goal.data["goal_progress"]] == [16.67, 16.67]
    assert "monthly_savings_capacity" not in goal.data
    assert not goal.data.get("needs_input")
    assert "remaining SGD 3000.00" in response.answer
    assert "16.67%" in response.answer
    assert any(event["event_type"] == "task.capacity_requirement.evaluated"
               and event["details"]["reason_code"] == "GOAL_CAPACITY_NOT_REQUIRED"
               for event in response.audit["events"])
    assert sum(call["system_prompt"].startswith("PROMPT_ID: goal_input_requirements")
               for call in gateway.calls) == 1


@pytest.mark.parametrize("message", [
    "Can I afford to fund my goals together?",
    "Is my current monthly pool enough to achieve all my goals?",
    "Calculate contributions for my saved goals and assess whether they are feasible together.",
])
def test_feasibility_retains_required_capacity_and_shared_pool(message):
    response = run(request(message, ["goal_strategy"], capacity=True))
    assert not response.blocked
    assert response.selected_agents == [AgentName.GOAL_STRATEGY, AgentName.BUDGET]
    assert "monthly_savings_capacity" in {edge["capability"] for edge in response.audit["dependency_edges"]}
    assert "transaction_category_totals" not in {edge["capability"] for edge in response.audit["dependency_edges"]}
    goal = next(result for result in response.agent_results if result.agent == AgentName.GOAL_STRATEGY)
    assert goal.data["combined_feasibility"]["monthly_shortfall"] == 300


def test_arithmetic_does_not_accept_unrequested_capacity_from_another_part():
    response = run(request(
        "Explain my budget savings capacity. Independently calculate contributions for my saved goals.",
        ["budget", "goal_strategy"], capacity=True,
    ))
    assert not response.blocked
    assert response.audit["dependency_edges"] == []
    goal = next(result for result in response.agent_results if result.agent == AgentName.GOAL_STRATEGY)
    assert "combined_feasibility" not in goal.data
    assert "monthly_savings_capacity" not in goal.data


def test_preselected_budget_is_not_forced_to_require_income_by_goal_arithmetic():
    response = run(request(
        "Explain budgeting in general. Independently calculate contributions for my saved goals.",
        ["budget", "goal_strategy"],
    ))
    assert not response.blocked
    assert response.audit["dependency_edges"] == []
    assert not any(result.data.get("needs_input") for result in response.agent_results)
    budget = next(result for result in response.agent_results if result.agent == AgentName.BUDGET)
    assert budget.data["calculation_status"] == "no_financial_inputs"


@pytest.mark.parametrize("message", [
    "Analyze my spending by category. Independently explain budgeting in general.",
    "Analyze my transactions by category. Separately explain my budget's savings capacity.",
])
def test_independent_spending_question_does_not_create_budget_edge(message):
    response = run(request(message, ["spending", "budget"], capacity=True))
    assert not response.blocked
    assert response.audit["dependency_edges"] == []
    assert response.selected_agents == [AgentName.SPENDING, AgentName.BUDGET]


def test_spending_informed_goal_feasibility_retains_chain():
    response = run(request("Use my spending patterns to assess whether I can fund my saved goals.",
                           ["goal_strategy"], capacity=True))
    assert not response.blocked
    assert response.selected_agents == [AgentName.GOAL_STRATEGY, AgentName.BUDGET, AgentName.SPENDING]
    assert {edge["capability"] for edge in response.audit["dependency_edges"]} == {
        "monthly_savings_capacity", "transaction_category_totals",
    }


def test_required_provider_is_reused_and_classification_is_not_repeated_on_resume():
    gateway = RecordingGateway()
    response = run(request("Assess my goals against my budget's savings capacity.",
                           ["budget", "goal_strategy"], capacity=True), gateway)
    assert not response.blocked
    assert any(item["resolution"] == "reused" and item["capability"] == "monthly_savings_capacity"
               for item in response.audit["dependency_resolutions"])
    for component in ("agent_budget", "goal_input_requirements"):
        assert sum(call["system_prompt"].startswith(f"PROMPT_ID: {component}")
                   for call in gateway.calls) == 1


def test_semantic_goal_decision_handles_paraphrases_without_keyword_matching():
    class SemanticGateway(RecordingGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: goal_input_requirements"):
                self.calls.append(kwargs)
                return json.dumps({"requires_capacity": False})
            return super().generate(**kwargs)

    response = run(request("Break each saved goal into the amount still outstanding and the equal instalments needed.",
                           ["goal_strategy"]), SemanticGateway())
    assert not response.blocked
    assert response.selected_agents == [AgentName.GOAL_STRATEGY]
    assert response.audit["dependency_edges"] == []


def test_saved_goal_arithmetic_and_independent_specialists_execute_concurrently():
    barrier = Barrier(3, timeout=5)

    class ConcurrentGateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].splitlines()[0] in {
                "PROMPT_ID: agent_spending", "PROMPT_ID: agent_budget", "PROMPT_ID: agent_goal_strategy",
            }:
                barrier.wait()
            return super().generate(**kwargs)

    response = run(request(
        "Analyze my spending by category. Independently explain budgeting in general. "
        "Separately calculate contributions for each saved goal.",
        ["spending", "budget", "goal_strategy"],
    ), ConcurrentGateway())
    assert not response.blocked
    assert response.audit["dependency_edges"] == []
    assert len(response.selected_agents) == 3


def test_goal_arithmetic_does_not_require_budget_even_when_income_is_known():
    req = request("Calculate contributions for my saved goals.", ["goal_strategy"], capacity=True)
    req.snapshot.recent_transactions = []
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture", )).handle(
        req,
    )
    assert response.selected_agents == [AgentName.GOAL_STRATEGY]
    assert response.audit["dependency_edges"] == []


def test_direct_goal_spending_edge_remains_unauthorized():
    with pytest.raises(CapabilityRegistryError, match="cannot request"):
        CapabilityRegistry().authorize(AgentName.GOAL_STRATEGY, CapabilityName.TRANSACTION_CATEGORY_TOTALS)


@pytest.mark.parametrize("value", ["false", None, 0])
def test_invalid_goal_requirement_cannot_run_financial_tasks(value):
    class InvalidGateway(RecordingGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: goal_input_requirements"):
                self.calls.append(kwargs)
                return json.dumps({"requires_capacity": value})
            return super().generate(**kwargs)

    gateway = InvalidGateway()
    with pytest.raises(ModelGatewayError) as failed:
        run(request("Assess whether I can fund my goals.", ["goal_strategy"], capacity=True), gateway)
    assert failed.value.code == "INVALID_STRUCTURED_RESPONSE"
    assert sum(call["system_prompt"].startswith("PROMPT_ID: goal_input_requirements")
               for call in gateway.calls) == 2
    assert not any(call["system_prompt"].startswith("PROMPT_ID: agent_") for call in gateway.calls)
