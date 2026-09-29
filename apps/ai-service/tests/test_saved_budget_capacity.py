from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.orchestrator import AgentOrchestrator

CAPACITY = {"source": "confirmed_plan", "period_start": "2026-10-01", "currency": "SGD",
            "take_home_income": 4000, "planned_expenses": 2000, "estimated_savings_capacity": 700,
            "unallocated_income": 1300, "calculation_method": "Confirmed monthly savings allocation", "budget_method": "flexible"}


def test_goal_uses_confirmed_pool_without_profile_income_or_double_subtraction():
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(CoachRequest(
        user_id="u", session_id="s", message="Are my goals affordable?", requested_agents=["goal_strategy"],
        saved_budget_capacity=CAPACITY, snapshot={"goals": [
            {"name": "Trip", "target_amount": {"amount": 6000}, "target_months": 12},
            {"name": "Course", "target_amount": {"amount": 6000}, "target_months": 12},
        ]},
    ))
    goal = next(item for item in response.agent_results if item.agent.value == "goal_strategy")
    assert not response.blocked
    assert goal.data["monthly_savings_capacity"]["estimated_savings_capacity"] == 700
    assert goal.data["combined_feasibility"]["monthly_shortfall"] == 300
    budget = next(item for item in response.agent_results if item.agent.value == "budget")
    assert budget.data["savings"] == 700
    assert "needs" not in budget.data


def test_unavailable_plan_has_explicit_fallback_source():
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(CoachRequest(
        user_id="u", session_id="s", message="Explain my budget", requested_agents=["budget"],
        snapshot={"monthly_income": {"amount": 4000}},
        saved_budget_capacity={"source": "unavailable", "period_start": "2026-10-01", "reason": "No confirmed plan"},
    ))
    result = next(item for item in response.agent_results if item.agent.value == "budget")
    assert result.data["capacity"]["source"] == "illustrative_fallback"
    assert result.data["capacity"]["estimated_savings_capacity"] == 800
