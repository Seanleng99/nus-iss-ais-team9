"""Select owned plan and expense evidence once, before specialist scheduling."""

from datetime import date
from decimal import Decimal

from coach_math.budget_scope import (
    BudgetScope,
    month_number,
    resolve_budget_periods,
    scoped_capacity,
)


def scope_budget_request(request, decision):
    context = dict(request.budget_context)
    capacities = context.pop("capacity_by_period", {})
    plans = context.pop("budgets_by_period", {})
    spending = context.pop("spending_by_period", None)
    available = sorted(set(plans) | set(capacities) | set(context.get("budget_periods", [])))
    capacity = scoped_capacity(
        request.saved_budget_capacity,
        capacities,
        decision.budget_scope,
        unclear=decision.budget_scope_unclear,
    )
    scope = decision.budget_scope or BudgetScope()
    default = (
        context.get("selected_period")
        or request.snapshot.period_start
        or capacity.get("period_start")
    )
    periods = (
        []
        if decision.budget_scope_unclear or (scope.kind == "default" and not default)
        else resolve_budget_periods(
            scope,
            date.fromisoformat(default) if default else None,
            [date.fromisoformat(p) for p in available],
        )
    )
    if decision.budget_scope is not None:
        context["resolved_scope"] = scope.model_dump(mode="json")
    if scope.kind != "default" or decision.budget_scope_unclear:
        context.pop("selected_budget", None)
        context.pop("selected_period", None)
        if len(periods) == 1:
            context["selected_period"] = str(periods[0])
            if str(periods[0]) in plans:
                context["selected_budget"] = plans[str(periods[0])]
    if decision.budget_scope_unclear:
        context["scope_unclear"] = True
    if plans and periods:
        context["scoped_budgets"] = [
            plans.get(str(p), {"period_start": str(p), "status": "missing"}) for p in periods
        ]

    snapshot = request.snapshot
    if spending is not None and periods:
        first = month_number(periods[0])
        history_periods = [date(n // 12, n % 12 + 1, 1) for n in range(max(12, first - 6), first)]
        rows = [_expense_month(spending, str(p)) for p in periods]
        history = [spending[str(p)] for p in history_periods if str(p) in spending]
        scoped = {
            "periods": rows,
            "history": history,
            "currency": "SGD",
            "category_totals": _totals(rows),
            "transaction_count": sum(r["transaction_count"] for r in rows),
            "historical_transaction_count": sum(r["transaction_count"] for r in history),
            "records_complete": False,
            "recorded_totals_complete": True,
            "scope": scope.model_dump(mode="json"),
            "caveat": "Owned recorded gross expenses; household coverage is unconfirmed. Refund adjustments are handled by the budget review workflow. These totals are not available cash.",
        }
        context["spending_context"] = scoped
        # Planning suggestions use the target month's preceding calendar months.
        context["recorded_spending"] = [
            {
                "period_start": r["period_start"],
                "currency": "SGD",
                "categories": r["category_totals"],
                "coverage": "unconfirmed",
            }
            for r in history
            if month_number(date.fromisoformat(r["period_start"])) >= first - 3
        ]
        if decision.budget_scope is not None or any(
            a.value in {"budget", "goal_strategy"} for a in decision.selected_agents
        ):
            transaction_context = {**snapshot.transaction_context, "budget_spending_scope": scoped}
            snapshot = snapshot.model_copy(update={"transaction_context": transaction_context})
    if scope.kind != "default" or decision.budget_scope_unclear:
        # Repartition only dated supplied records. Missing raw history is never
        # replaced by another month's rows; backend aggregates cover older months.
        records = [*snapshot.recent_transactions, *snapshot.historical_transactions]
        wanted = set(periods)
        recent = [t for t in records if date.fromisoformat(t.occurred_on).replace(day=1) in wanted]
        history = [t for t in records if periods and date.fromisoformat(t.occurred_on) < periods[0]]
        snapshot = snapshot.model_copy(
            update={
                "recent_transactions": recent,
                "historical_transactions": history,
                "period_start": str(periods[-1]) if periods else None,
                "transaction_context": {
                    **snapshot.transaction_context,
                    "requested_budget_scope": scope.model_dump(mode="json"),
                    "scope_unclear": decision.budget_scope_unclear,
                },
            }
        )
    return request.model_copy(
        update={"budget_context": context, "saved_budget_capacity": capacity, "snapshot": snapshot}
    )


def _expense_month(catalog, period):
    return catalog.get(
        period,
        {
            "period_start": period,
            "category_totals": {},
            "transaction_count": 0,
            "currency": "SGD",
            "excluded_currencies": [],
            "first_recorded_on": None,
            "last_recorded_on": None,
        },
    )


def _totals(rows):
    names = {name for row in rows for name in row["category_totals"]}
    return {
        name: float(
            sum((Decimal(str(row["category_totals"].get(name, 0))) for row in rows), Decimal(0))
        )
        for name in sorted(names)
    }
