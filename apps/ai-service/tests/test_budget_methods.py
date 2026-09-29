import pytest
from pydantic import ValidationError

from app.agents.budget_capture import BudgetDraft
from app.agents.budget_methods import BudgetMethod
from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.budget_fixture import fixture_budget_draft
from app.orchestrator import AgentOrchestrator


def test_offline_what_if_keeps_base_savings_and_income_unchanged():
    pending = {
        "period_start": "2026-10-01",
        "currency": "SGD",
        "categories": [{"category": "food", "limit_amount": 500}],
        "planning": {"take_home_income": 4000, "income_basis": "take_home", "savings_target": 800},
    }
    result = fixture_budget_draft(
        {"message": "scenario More saving: savings=1000", "pending_draft": pending}
    )
    assert result["planning"]["savings_target"] == 800
    assert result["action"] == "compare"
    assert result["scenarios"] == [{"name": "More saving", "savings_target": 1000}]
    BudgetDraft.model_validate(result)


def test_method_schema_does_not_guess_category_classifications():
    method = BudgetMethod(name="50_30_20")
    assert method.category_groups == {}
    assert "housing" in method.questions(["housing"])[0]
    with pytest.raises(ValidationError):
        BudgetMethod(name="automatic")


def test_comparison_intent_routes_to_budget_planning():
    result = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="u",
            session_id="s",
            message="Compare my budget using 80/20 for October 2026 SGD; take home income: 4000; savings: 800; food: 500",
        )
    )
    budget = next(item for item in result.agent_results if item.agent.value == "budget")
    assert budget.data["budget_draft"]["planning"]["method"]["name"] == "80_20"
    assert budget.data["budget_draft"]["action"] == "compare"
    assert budget.data["planning_analysis"]["version"] == "budget-planning-v2"
