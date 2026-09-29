"""Authoritative checks and summaries for first-stage Coach budget planning."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from app.api.financial_schemas import BudgetPlanSettings
from app.infrastructure.repositories import SQLAlchemyBudgetRepository, SQLAlchemyUserRepository


class PlanningInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take_home_income: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    income_basis: Literal["take_home", "gross", "unknown"] = "unknown"
    savings_target: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    expenses_confirmed: bool = False
    use_recorded_spending: bool = False

    def questions(self):
        result = []
        if self.take_home_income is None or self.income_basis != "take_home":
            result.append(
                "What is your monthly take-home income in SGD, after payroll deductions? Profile income is not assumed to be take-home."
            )
        if self.savings_target is None:
            result.append(
                "How much do you want to set aside in savings this month? State 0 if you do not want a savings allocation."
            )
        if not self.expenses_confirmed:
            result.append(
                "Do these category limits include all your expenses, including essential commitments, debt payments and irregular costs? Supply missing monthly amounts, or reply 'all expenses included'."
            )
        return result

    def settings(self):
        return BudgetPlanSettings(
            take_home_income=self.take_home_income,
            savings_target=self.savings_target,
            income_basis=self.income_basis,
            expenses_confirmed=self.expenses_confirmed,
        )


def build_planning_context(session, user_id: str, *, today: date | None = None) -> dict:
    today = today or datetime.now(ZoneInfo("Asia/Singapore")).date()
    repository = SQLAlchemyBudgetRepository(session)
    history = []
    # Aggregate complete calendar periods; completeness of the records is still unknown.
    for offset in range(1, 4):
        year, month_index = divmod(today.year * 12 + today.month - 1 - offset, 12)
        period = date(year, month_index + 1, 1)
        totals = repository.spending_by_category(user_id, period, currency="SGD")
        if totals:
            history.append(
                {
                    "period_start": period.isoformat(),
                    "currency": "SGD",
                    "categories": totals,
                    "coverage": "unconfirmed",
                }
            )
    profile = SQLAlchemyUserRepository(session).get_profile(user_id)
    return {
        "recorded_spending": history,
        "profile_income": {
            "amount": float(profile.monthly_income),
            "currency": profile.currency,
            "income_basis": "unconfirmed",
        }
        if profile and profile.monthly_income is not None
        else None,
    }


def affordability(categories: dict[str, float], planning) -> dict:
    expense_total = sum((Decimal(str(value)) for value in categories.values()), Decimal(0))
    balance = (
        Decimal(str(planning.take_home_income))
        - expense_total
        - Decimal(str(planning.savings_target))
    )
    return {
        "expense_total": float(expense_total),
        "unallocated": float(max(balance, Decimal(0))),
        "funding_gap": float(max(-balance, Decimal(0))),
    }


def describe_affordability(categories: dict[str, float], planning) -> tuple[str, bool]:
    result = affordability(categories, planning)
    text = (
        f"Take-home income: SGD {planning.take_home_income:,.2f}. "
        f"Planned expenses: SGD {result['expense_total']:,.2f}. "
        f"Savings allocation: SGD {planning.savings_target:,.2f} (separate from spending). "
    )
    if result["funding_gap"] > 0:
        return text + (
            f"Funding gap: SGD {result['funding_gap']:,.2f}. Nothing can be saved yet. "
            "Which amounts would you like to revise? I will not cut commitments or change your savings target automatically."
        ), False
    return text + f"Unallocated income: SGD {result['unallocated']:,.2f}.", True
