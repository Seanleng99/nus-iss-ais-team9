import json

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.orchestrator import AgentOrchestrator

OCT = {
    "source": "confirmed_plan",
    "period_start": "2026-10-01",
    "currency": "SGD",
    "take_home_income": 4000,
    "planned_expenses": 2000,
    "estimated_savings_capacity": 700,
    "unallocated_income": 1300,
    "calculation_method": "Confirmed savings allocation",
    "budget_method": "flexible",
}
NOV = {
    **OCT,
    "period_start": "2026-11-01",
    "estimated_savings_capacity": 1000,
    "unallocated_income": 1000,
}
CONTEXT = {
    "today": "2026-10-05",
    "selected_period": "2026-10-01",
    "request_scope": {"operations": ["budgets"]},
    "capacity_by_period": {OCT["period_start"]: OCT, NOV["period_start"]: NOV},
    "budget_periods": [OCT["period_start"], NOV["period_start"]],
}


def ask(message, **values):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="budget-u",
            session_id="budget-chat",
            message=message,
            budget_context=CONTEXT,
            saved_budget_capacity=OCT,
            **values,
        )
    )


@pytest.mark.parametrize(
    "message,action,kind",
    [
        ("Show all my saved budgets", "read", "all"),
        ("Compare my budgets from October through December 2026", "compare", "range"),
        ("Summarise my budgets for 2026", "read", "range"),
        ("Change my budgets for October through December 2026; food: 600", "edit", "range"),
        ("Remove the food limit from my November 2026 budget", "edit", "periods"),
        ("Delete my November 2026 budget", "delete", "periods"),
    ],
)
def test_records_route_and_extract_without_profile_income(message, action, kind):
    response = ask(message)
    assert not response.blocked
    result = next(r for r in response.agent_results if r.agent.value == "budget")
    draft = result.data["budget_draft"]
    assert draft["action"] == "workspace"
    assert draft["workspace"]["operation"] == "budgets"
    command = json.loads(draft["workspace"]["payload_json"])
    assert command["action"] == action
    assert command["scope"]["kind"] == kind
    assert "planning_analysis" not in result.data


def test_goal_capacity_uses_explicit_month_instead_of_ui_default():
    response = ask(
        "Are my goals affordable using my November 2026 budget?",
        snapshot={
            "goals": [{"name": "Course", "target_amount": {"amount": 10800}, "target_months": 12}]
        },
    )
    assert not response.blocked
    goal = next(r for r in response.agent_results if r.agent.value == "goal_strategy")
    assert goal.data["monthly_savings_capacity"]["period_start"] == "2026-11-01"
    assert goal.data["combined_feasibility"]["monthly_capacity"] == 1000
    assert goal.data["combined_feasibility"]["status"] == "feasible"


def test_explicit_specialist_selection_still_resolves_calendar_scope():
    response = ask(
        "Are my goals affordable using my November 2026 budget?",
        requested_agents=["goal_strategy"],
        snapshot={
            "goals": [{"name": "Course", "target_amount": {"amount": 10800}, "target_months": 12}]
        },
    )
    goal = next(r for r in response.agent_results if r.agent.value == "goal_strategy")
    assert goal.data["monthly_savings_capacity"]["period_start"] == "2026-11-01"


def test_goal_range_keeps_each_month_pool_and_missing_month_explicit():
    response = ask(
        "Are my goals affordable using my budgets from October through December 2026?",
        snapshot={
            "goals": [{"name": "Course", "target_amount": {"amount": 10800}, "target_months": 12}]
        },
    )
    assert not response.blocked
    goal = next(r for r in response.agent_results if r.agent.value == "goal_strategy")
    rows = goal.data["period_feasibility"]
    assert [row["status"] for row in rows] == ["shortfall", "feasible", "unavailable"]
    assert rows[0]["monthly_capacity"] == 700 and rows[1]["monthly_capacity"] == 1000
    assert rows[2]["monthly_capacity"] is None and rows[2]["monthly_shortfall"] is None
    assert goal.data["monthly_savings_capacity"]["known_savings_total"] == 1700
    assert "combined_feasibility" not in goal.data


def test_ambiguous_date_cannot_fall_back_to_default_month():
    response = ask("Delete my November budget")
    draft = next(r for r in response.agent_results if r.agent.value == "budget").data[
        "budget_draft"
    ]
    assert draft["questions"]
    assert response.audit["turn_decision"]["budget_scope_unclear"]


def test_explicit_missing_plan_does_not_use_another_month_or_profile_fallback():
    response = ask(
        "Calculate my savings capacity using my December 2026 budget",
        snapshot={"monthly_income": {"amount": 6000}},
    )
    budget = next(r for r in response.agent_results if r.agent.value == "budget")
    assert not response.blocked
    assert budget.data["capacity_source"] == "unavailable"
    assert budget.data["requested_capacity"]["period_start"] == "2026-12-01"
    assert "savings" not in budget.data


def test_goal_missing_requested_plan_cannot_borrow_default_pool():
    response = ask(
        "Are my goals affordable using my December 2026 budget?",
        snapshot={
            "monthly_income": {"amount": 6000},
            "goals": [{"name": "Course", "target_amount": {"amount": 10800}, "target_months": 12}],
        },
    )
    goal = next(r for r in response.agent_results if r.agent.value == "goal_strategy")
    assert goal.data["monthly_savings_capacity"]["source"] == "unavailable"
    assert goal.data["monthly_savings_capacity"]["estimated_savings_capacity"] is None
    assert "combined_feasibility" not in goal.data
