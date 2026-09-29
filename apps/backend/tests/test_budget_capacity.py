from datetime import date

from app.api.financial_schemas import BudgetUpsert
from app.infrastructure.repositories import SQLAlchemyBudgetRepository
from app.services.budget_capacity import build_capacity_context


def test_capacity_is_owned_period_specific_and_uses_confirmed_savings(db_session_factory):
    with db_session_factory() as session:
        SQLAlchemyBudgetRepository(session).upsert("u1", BudgetUpsert.model_validate({
            "period_start": "2026-10-01", "categories": [{"category": "housing", "limit_amount": 2000}],
            "planning": {"take_home_income": 4000, "savings_target": 700},
        }))
        result = build_capacity_context(session, "u1", date(2026, 10, 1))
        assert result["estimated_savings_capacity"] == 700
        assert result["unallocated_income"] == 1300
        assert result["planned_expenses"] == 2000
        assert build_capacity_context(session, "u2", date(2026, 10, 1))["source"] == "unavailable"
        assert build_capacity_context(session, "u1", date(2026, 11, 1))["source"] == "unavailable"


def test_manual_budget_does_not_establish_confirmed_income(db_session_factory):
    with db_session_factory() as session:
        SQLAlchemyBudgetRepository(session).upsert("u1", BudgetUpsert.model_validate({"period_start": "2026-10-01", "categories": []}))
        assert build_capacity_context(session, "u1", today=date(2026, 10, 15))["source"] == "unavailable"
