from datetime import date

from app.agents.budget_capture import BudgetDraft
from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.orchestrator import AgentOrchestrator
from app.tools.budget_planner import propose_budget


def draft(**updates):
    data = {
        "period_start": "2026-10-01",
        "currency": "SGD",
        "categories": [{"category": "housing", "limit_amount": 1500}],
        "planning": {
            "take_home_income": 4000,
            "income_basis": "take_home",
            "savings_target": 800,
            "expenses_confirmed": True,
            "use_recorded_spending": True,
        },
    }
    data.update(updates)
    return BudgetDraft.model_validate(data)


CONTEXT = {
    "recorded_spending": [
        {
            "period_start": "2026-09-01",
            "currency": "SGD",
            "categories": {"housing": 1600, "food": 500, "pet care": 120},
        },
        {"period_start": "2026-08-01", "currency": "SGD", "categories": {"food": 900}},
    ]
}


def test_proposal_preserves_user_amounts_and_uses_one_recorded_month():
    plan = draft()
    analysis = propose_budget(plan, CONTEXT)
    assert {row.category: row.limit_amount for row in plan.categories} == {
        "housing": 1500,
        "food": 500,
        "pet care": 120,
    }
    assert plan.categories[0].source == "user"
    assert plan.categories[1].source == "recorded_spending"
    assert plan.categories[1].reference_period == date(2026, 9, 1)
    assert not plan.planning.expenses_confirmed
    assert analysis["expense_total"] == 2120
    assert analysis["unallocated"] == 1080
    assert analysis["funding_gap"] == 0
    assert "incomplete" in analysis["warnings"][0]


def test_shortfall_is_reported_without_cutting_expenses_or_savings():
    plan = draft(categories=[{"category": "commitments", "limit_amount": 3500}])
    plan.planning.use_recorded_spending = False
    result = propose_budget(plan, CONTEXT)
    assert result["funding_gap"] == 300
    assert plan.categories[0].limit_amount == 3500
    assert plan.planning.savings_target == 800


def test_no_income_or_savings_are_inferred_and_gross_is_not_available_income():
    plan = draft(planning={"income_basis": "gross", "take_home_income": 4000})
    result = propose_budget(plan, CONTEXT)
    assert result["funding_gap"] is None
    assert plan.planning.savings_target is None
    plan.planning.savings_target = 800
    assert propose_budget(plan, CONTEXT)["unallocated"] is None


def test_history_never_overwrites_ambiguous_user_amounts():
    plan = draft(categories=[{"category": "food", "limit_amount": None}])
    result = propose_budget(plan, CONTEXT)
    assert plan.categories[0].limit_amount is None
    assert result["funding_gap"] is None


def test_followup_keeps_proposals_and_does_not_reinflate_corrected_limits():
    plan = draft()
    propose_budget(plan, CONTEXT)
    pending = plan.model_dump(mode="json")
    plan.categories[1].limit_amount = 400
    plan.categories[1].source = "user"
    plan.planning.expenses_confirmed = True
    result = propose_budget(plan, CONTEXT, pending)
    assert plan.categories[1].limit_amount == 400
    assert plan.planning.expenses_confirmed
    assert result["unallocated"] == 1180


def test_missing_month_does_not_select_a_history_period():
    plan = draft(period_start=None)
    propose_budget(plan, CONTEXT)
    assert len(plan.categories) == 1
    pending = plan.model_dump(mode="json")
    plan.period_start = date(2026, 10, 1)
    propose_budget(plan, CONTEXT, pending)
    assert len(plan.categories) == 3


def test_planning_route_without_income_asks_details_instead_of_percentage_baseline():
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="u1", session_id="planning", message="Help me build a realistic budget"
        )
    )
    result = next(item for item in response.agent_results if item.agent.value == "budget")
    assert not response.blocked
    assert result.data["budget_draft"]["planning"]["take_home_income"] is None
    assert result.data["planning_analysis"]["version"] == "budget-planning-v2"
    assert "take-home" in result.summary
    assert "needs" not in result.data


def test_pending_plan_is_routed_back_for_clarification_with_minimal_context():
    pending = draft().model_dump(mode="json")
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="u1",
            session_id="planning",
            message="all expenses included",
            pending_budget=pending,
            budget_context=CONTEXT,
        )
    )
    result = next(item for item in response.agent_results if item.agent.value == "budget")
    assert not response.blocked
    assert result.data["budget_draft"]["planning"]["expenses_confirmed"]


def test_savings_transfers_and_other_currencies_are_not_proposed_as_sgd_expenses():
    plan = draft()
    context = {
        "recorded_spending": [
            {"period_start": "2026-09-01", "currency": "USD", "categories": {"food": 999}},
            {
                "period_start": "2026-08-01",
                "currency": "SGD",
                "categories": {"food": 500, "savings": 800},
            },
        ]
    }
    result = propose_budget(plan, context)
    assert {row.category: row.limit_amount for row in plan.categories} == {
        "housing": 1500,
        "food": 500,
    }
    assert result["unallocated"] == 1200
    assert any("excluded" in warning for warning in result["warnings"])
