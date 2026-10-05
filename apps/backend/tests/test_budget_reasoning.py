from datetime import date

from app.api.financial_schemas import BudgetUpsert, TransactionCreate
from app.infrastructure.models import TransactionRecord
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyTransactionRepository,
)
from app.services.budget_constraints import AllocationPolicy, save_policy
from app.services.budget_planning import build_planning_context
from app.services.budget_reasoning import spending_catalog


def test_spending_catalog_is_owned_and_keeps_currencies_and_income_separate(db_session_factory):
    with db_session_factory() as session:
        budgets = SQLAlchemyBudgetRepository(session)
        budgets.upsert("u", BudgetUpsert(period_start="2026-11-01", categories=[]))
        budgets.upsert("other", BudgetUpsert(period_start="2026-11-01", categories=[]))
        transactions = SQLAlchemyTransactionRepository(session)
        for user, amount, currency, kind in [
            ("u", 200, "SGD", "expense"),
            ("u", 10, "USD", "expense"),
            ("u", 4000, "SGD", "income"),
            ("other", 999, "SGD", "expense"),
        ]:
            if currency == "SGD":
                transactions.create(
                    user,
                    TransactionCreate(
                        description="Private detail",
                        category="food",
                        amount={"amount": amount},
                        occurred_on="2020-11-03",
                        transaction_type=kind,
                    ),
                )
            else:
                session.add(
                    TransactionRecord(
                        user_id=user,
                        description="Legacy",
                        category="food",
                        amount=amount,
                        currency=currency,
                        occurred_on=date(2020, 11, 3),
                    )
                )
        session.flush()
        data = spending_catalog(session, "u")
        assert data["2020-11-01"]["category_totals"] == {"food": 200}
        assert data["2020-11-01"]["transaction_count"] == 1
        assert data["2020-11-01"]["excluded_currencies"] == ["USD"]
        assert "Private detail" not in str(data)


def test_saved_context_preserves_each_months_commitments_and_category_only_plan(db_session_factory):
    with db_session_factory() as session:
        budgets = SQLAlchemyBudgetRepository(session)
        budgets.upsert(
            "u",
            BudgetUpsert(
                period_start="2026-11-01",
                categories=[{"category": "food", "limit_amount": 600}],
                planning={"take_home_income": 4000, "savings_target": 700},
            ),
        )
        budgets.upsert(
            "u",
            BudgetUpsert(
                period_start="2026-10-01",
                categories=[{"category": "transport", "limit_amount": 200}],
            ),
        )
        save_policy(
            session,
            "u",
            AllocationPolicy(
                period_start="2026-11-01", confirmed=True, protected_categories=["food"]
            ),
        )
        data = build_planning_context(session, "u", period=date(2026, 10, 1))
        assert data["selected_budget"]["categories"] == {"transport": 200}
        november = data["budgets_by_period"]["2026-11-01"]
        assert november["categories"] == {"food": 600}
        assert november["restrictions"]["category_minimums"] == {"food": 600}
        assert november["affordability"]["unallocated"] == 2700
