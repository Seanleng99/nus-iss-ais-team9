"""Owned, confirmed-plan capacity shared with specialist agents."""
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.api.financial_schemas import BudgetUpsert
from app.infrastructure.repositories import SQLAlchemyBudgetRepository
from app.services.budget_planning import affordability


def build_capacity_context(session, user_id, period_start=None, *, today=None):
    today = today or datetime.now(ZoneInfo("Asia/Singapore")).date()
    period = period_start or today.replace(day=1)
    context = {"period_start": period.isoformat(), "source": "unavailable", "reason": "No confirmed planning settings for this month."}
    record = SQLAlchemyBudgetRepository(session).get(user_id, period)
    if not record or not record.planning:
        return context
    try:
        plan = BudgetUpsert.model_validate({"period_start": period, "currency": record.currency, "planning": record.planning,
                                           "categories": [{"category": row.category, "limit_amount": row.limit_amount} for row in record.categories]})
    except ValidationError:
        return {**context, "reason": "Saved planning settings require correction before capacity can be used."}
    totals = affordability({row.category: row.limit_amount for row in plan.categories}, plan.planning)
    return {"source": "confirmed_plan", "period_start": period.isoformat(), "currency": "SGD",
            "take_home_income": plan.planning.take_home_income, "planned_expenses": totals["expense_total"],
            "estimated_savings_capacity": plan.planning.savings_target, "unallocated_income": totals["unallocated"],
            "budget_method": plan.planning.method.name,
            "calculation_method": "Confirmed monthly savings allocation; unallocated income is not assigned to goals.",
            "caveat": "This is a planned monthly pool, not an observed balance or a guarantee of future income. Goals share this pool."}
