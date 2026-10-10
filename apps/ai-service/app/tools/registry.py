from datetime import date
from decimal import Decimal

from coach_math.budget_baseline import recurring_month_total

from app.core.guardrails import validate_tool_permission
from app.core.schemas import AgentName, UserFinancialSnapshot
from app.core.telemetry import log_event, trace_method


@trace_method
def summarize_transactions(snapshot: UserFinancialSnapshot) -> dict[str, float]:
    log_event("VV entering ", "app.tools.registry", "summarize_transactions")
    totals: dict[str, float] = {}
    for transaction in snapshot.recent_transactions:
        totals[transaction.category] = totals.get(transaction.category, 0.0) + transaction.amount.amount
    return totals


@trace_method
def calculate_budget(snapshot: UserFinancialSnapshot) -> dict:
    log_event("VV entering ", "app.tools.registry", "calculate_budget")
    income = snapshot.monthly_income.amount if snapshot.monthly_income else 0.0
    evidence = recurring_month_total(snapshot.recurring_expenses, snapshot.period_start)
    recurring = evidence["monthly_amount"]
    if recurring is None:
        return {
            "income": income, "recurring_expenses": None, "disposable_income": None,
            "needs": None, "wants": None, "savings": None,
            "period_start": evidence["period_start"], "recurring_evidence": evidence,
            "calculation_status": "recurring_terms_unconfirmed",
            "method": "Savings capacity unavailable until recurring payment frequency and obligation identity are confirmed.",
            "questions": ["Confirm the frequency of recurring expenses and identify repeated payments for the same obligation before calculating monthly capacity."],
        }
    disposable = max(income - recurring, 0.0)
    return {
        "income": round(income, 2),
        "recurring_expenses": round(recurring, 2),
        "disposable_income": round(disposable, 2),
        "needs": round(disposable * 0.5, 2),
        "wants": round(disposable * 0.3, 2),
        "savings": round(disposable * 0.2, 2),
        "funding_gap": round(max(recurring - income, 0.0), 2),
        "period_start": evidence["period_start"], "recurring_evidence": evidence,
        "method": "50/30/20 baseline after recurring expenses",
    }


@trace_method
def project_goals(snapshot: UserFinancialSnapshot) -> list[dict[str, float | str]]:
    log_event("VV entering ", "app.tools.registry", "project_goals")
    projections: list[dict[str, float | str]] = []
    for goal in snapshot.goals:
        remaining = max(goal.target_amount.amount - goal.current_amount.amount, 0.0)
        monthly_required = remaining / goal.target_months
        projections.append(
            {
                "name": goal.name,
                "currency": goal.target_amount.currency,
                "remaining": round(remaining, 2),
                "target_months": goal.target_months,
                "monthly_required": round(monthly_required, 2),
            }
        )
    return projections


@trace_method
def summarize_emergency_fund(snapshot: UserFinancialSnapshot) -> dict:
    # Logged rows are not evidence of a complete month's essential expenses.
    # Recurring rows may also occur in recent_transactions; never add both lists.
    log_event("VV entering ", "app.tools.registry", "summarize_emergency_fund")
    totals: dict[tuple[str, str], Decimal] = {}
    invalid_dates = 0
    for transaction in snapshot.recent_transactions:
        try:
            month = date.fromisoformat(transaction.occurred_on).strftime("%Y-%m")
        except ValueError:
            invalid_dates += 1
            continue
        key = (month, transaction.amount.currency)
        totals[key] = totals.get(key, Decimal(0)) + Decimal(str(transaction.amount.amount))
    return {
        "monthly_logged_spending": [
            {"month": month, "currency": currency, "amount": float(total.quantize(Decimal("0.01")))}
            for (month, currency), total in sorted(totals.items())
        ],
        "saved_goals": [goal.model_dump(mode="json") for goal in snapshot.goals],
        "expense_coverage": "unconfirmed",
        "invalid_transaction_dates": invalid_dates,
        "method": (
            "Sum recent_transactions once by calendar month and currency; no currency conversion. "
            "Recurring rows are not added because they may duplicate these transactions and have no cadence. "
            "Logged spending may be partial and includes unclassified needs and wants. "
            "Saved goal amounts are user records, not verified bank balances."
        ),
    }


@trace_method
def call_tool(agent: AgentName, tool_name: str, snapshot: UserFinancialSnapshot):
    log_event("VV entering ", "app.tools.registry", "call_tool")
    validate_tool_permission(agent, tool_name)
    if tool_name == "transaction_summarizer":
        return summarize_transactions(snapshot)
    if tool_name == "budget_calculator":
        return calculate_budget(snapshot)
    if tool_name == "goal_projection":
        return project_goals(snapshot)
    if tool_name == "emergency_fund_summary":
        return summarize_emergency_fund(snapshot)
    raise KeyError(f"Unknown tool: {tool_name}")
