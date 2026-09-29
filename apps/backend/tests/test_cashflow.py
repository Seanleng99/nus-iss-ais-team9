from datetime import date

from app.api.financial_schemas import ProfileUpsert, TransactionCreate
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyUserRepository,
)
from app.services.cashflow import CashflowSettings, Schedule, occurs, project_cashflow
from app.services.financial_workspace import write_section


def config(**updates):
    data = {
        "opening_on": "2026-10-01",
        "opening_balance": 1000,
        "confirmed": True,
        "schedules": [
            {
                "id": "rent",
                "name": "Rent",
                "category": "housing",
                "kind": "expense",
                "amount": 1500,
                "first_on": "2026-10-05",
                "frequency": "monthly",
            },
            {
                "id": "pay",
                "name": "Pay",
                "category": "salary",
                "kind": "income",
                "amount": 3000,
                "first_on": "2026-10-20",
                "frequency": "monthly",
            },
        ],
    }
    data.update(updates)
    return CashflowSettings.model_validate(data)


def test_month_balances_but_cash_runs_short_before_payday(db_session_factory):
    with db_session_factory() as session:
        write_section(session, "u", "cashflow", config().model_dump(mode="json"))
        result = project_cashflow(session, "u", date(2026, 10, 31), today=date(2026, 10, 1))
        assert result["first_shortfall_on"] == "2026-10-05"
        assert result["lowest_balance"] == -500
        assert result["closing_balance"] == 2500
        assert project_cashflow(session, "other", date(2026, 10, 31))["needs_input"]


def test_settled_bill_not_double_counted_and_income_refund_transfer_typed(db_session_factory):
    with db_session_factory() as session:
        plan = config()
        plan.schedules[0].settled_dates = [date(2026, 10, 5)]
        write_section(session, "u", "cashflow", plan.model_dump(mode="json"))
        repo = SQLAlchemyTransactionRepository(session)
        for kind, amount in [("expense", 1500), ("income", 100), ("refund", 50), ("transfer", 900)]:
            repo.create(
                "u",
                TransactionCreate(
                    description=kind,
                    category="housing",
                    amount={"amount": amount},
                    occurred_on="2026-10-05",
                    transaction_type=kind,
                ),
            )
        result = project_cashflow(session, "u", date(2026, 10, 31), today=date(2026, 10, 6))
        assert result["closing_balance"] == 2650
        assert SQLAlchemyBudgetRepository(session).spending_by_category("u", date(2026, 10, 1)) == {
            "housing": 1500
        }
        SQLAlchemyUserRepository(session).upsert_profile("u", ProfileUpsert())
        snapshot = SQLAlchemyUserRepository(session).get_financial_snapshot("u")
        assert len(snapshot.recent_transactions) == 1


def test_month_end_clamps_without_losing_anchor_and_annual_leap_day():
    schedule = Schedule(
        id="a",
        name="a",
        category="a",
        kind="expense",
        amount=10,
        first_on="2024-01-31",
        frequency="monthly",
    )
    assert occurs(schedule, date(2024, 2, 29))
    assert occurs(schedule, date(2024, 3, 31))
    assert not occurs(schedule, date(2024, 3, 29))
    schedule.first_on = date(2024, 2, 29)
    schedule.frequency = "yearly"
    assert occurs(schedule, date(2025, 2, 28))


def test_cashflow_settings_follow_owner_export_and_deletion(db_session_factory):
    from app.infrastructure.models import PlanningPreferencesRecord

    with db_session_factory() as session:
        write_section(session, "u", "cashflow", config().model_dump(mode="json"))
        # ORM owner deletion cascades even in SQLite without foreign-key pragmas.
        from app.infrastructure.models import UserRecord

        session.delete(session.get(UserRecord, "u"))
        session.flush()
        assert session.get(PlanningPreferencesRecord, "u") is None
