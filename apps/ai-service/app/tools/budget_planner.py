"""Deterministic first-stage planning: explicit limits or recorded-spending proposals.

No percentage allocation, currency conversion, guessed commitments, or automatic cuts.
"""

from datetime import date
from decimal import Decimal

from app.agents.budget_capture import BudgetDraft, BudgetDraftCategory, PlanningInputs
from app.core.guardrails import validate_tool_permission
from app.core.schemas import AgentName
from app.core.telemetry import trace_method

PLANNER_VERSION = "budget-planning-v3"


def amount(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@trace_method
def propose_budget(draft: BudgetDraft, context: dict, pending: dict | None = None) -> dict:
    validate_tool_permission(AgentName.BUDGET, "budget_planner")
    if draft.planning is None:
        draft.planning = PlanningInputs()
    inputs = draft.planning
    warnings = []
    present = {" ".join((item.category or "").split()).lower() for item in draft.categories}
    for previous in (pending or {}).get("categories", []):
        name = " ".join((previous.get("category") or "").split()).lower()
        if name not in present:
            draft.categories.append(BudgetDraftCategory.model_validate(previous))
            present.add(name)
    # Preserve explicit user limits. History fills absent categories only, not ambiguous user amounts.
    if inputs.use_recorded_spending and not (pending or {}).get("planning"):
        candidates = [
            row
            for row in context.get("recorded_spending", [])
            if row.get("currency") == "SGD"
            and draft.period_start
            and date.fromisoformat(row["period_start"]) < draft.period_start
        ]
        if candidates:
            latest = max(candidates, key=lambda row: row["period_start"])
            transfer_names = {"savings", "emergency fund", "investments"}
            expense_categories = {
                name: value
                for name, value in latest["categories"].items()
                if name not in transfer_names
            }
            if len(expense_categories) != len(latest["categories"]):
                warnings.append(
                    "Recorded savings/investment categories were excluded from expense suggestions; confirm your separate savings allocation."
                )
            present = {" ".join((item.category or "").split()).lower() for item in draft.categories}
            if len(present | set(expense_categories)) > 50:
                draft.questions.append(
                    "Recorded spending would exceed 50 categories. Specify the categories to include instead."
                )
                return {
                    "version": PLANNER_VERSION,
                    "warnings": ["Too many categories for a single plan."],
                }
            for category, value in expense_categories.items():
                if category not in present and len(draft.categories) < 50:
                    draft.categories.append(
                        BudgetDraftCategory(
                            category=category,
                            limit_amount=value,
                            source="recorded_spending",
                            reference_period=latest["period_start"],
                        )
                    )
            # The user must review newly generated amounts before confirming expense coverage.
            inputs.expenses_confirmed = False
        else:
            warnings.append(
                "No earlier recorded SGD spending is available; provide category limits."
            )
    elif inputs.use_recorded_spending:
        # Add history on a follow-up that supplies the month or first requests spending proposals.
        previous = (pending or {}).get("planning") or {}
        if not previous.get("use_recorded_spending") or not (pending or {}).get("period_start"):
            return propose_budget(draft, context)
    if any(item.source == "recorded_spending" for item in draft.categories):
        warnings.append(
            "Recorded-spending suggestions may reflect incomplete records; they are not verified monthly needs. Recurring transaction rows are not added again."
        )
    complete_amounts = all(item.limit_amount is not None for item in draft.categories)
    expense_total = sum(
        (amount(item.limit_amount) for item in draft.categories if item.limit_amount is not None),
        Decimal(0),
    )
    balance = None
    if (
        draft.currency == "SGD"
        and inputs.income_basis == "take_home"
        and inputs.take_home_income is not None
        and inputs.savings_target is not None
        and complete_amounts
    ):
        balance = amount(inputs.take_home_income) - expense_total - amount(inputs.savings_target)
    return {
        "version": PLANNER_VERSION,
        "expense_total": float(expense_total),
        "unallocated": float(max(balance, Decimal(0))) if balance is not None else None,
        "funding_gap": float(max(-balance, Decimal(0))) if balance is not None else None,
        "warnings": warnings,
    }


def describe_plan(draft: BudgetDraft, analysis: dict) -> str:
    inputs = draft.planning
    currency = draft.currency or "currency unconfirmed"
    lines = [
        f"Unsaved budget proposal for {draft.period_start or 'a month still to be specified'}."
    ]
    for item in draft.categories:
        limit = (
            f"{currency} {item.limit_amount:,.2f}"
            if item.limit_amount is not None
            else "amount needed"
        )
        source = (
            f"recorded-spending suggestion ({item.reference_period})"
            if item.source == "recorded_spending"
            else "user-provided"
        )
        lines.append(f"{item.category or 'Category needed'}: {limit} ({source}).")
    if inputs.take_home_income is None or inputs.income_basis != "take_home":
        lines.append(
            "Please provide or confirm monthly take-home income; gross or unclassified profile income cannot be used."
        )
    else:
        lines.append(f"Confirmed take-home income: {currency} {inputs.take_home_income:,.2f}.")
    if inputs.savings_target is None:
        lines.append(
            "What monthly savings allocation do you want, including zero if that is your choice?"
        )
    else:
        lines.append(f"Separate savings allocation: {currency} {inputs.savings_target:,.2f}.")
    if not draft.categories:
        lines.append("Provide category limits or ask to use recorded spending as suggestions.")
    if not inputs.expenses_confirmed:
        lines.append(
            "Please confirm whether all essential commitments, debt payments and irregular costs are included, or supply missing monthly amounts."
        )
    if analysis.get("funding_gap"):
        lines.append(
            f"Funding gap: SGD {analysis['funding_gap']:,.2f}. Which amounts would you like to revise? No automatic cuts or savings changes were made."
        )
    elif analysis.get("unallocated") is not None:
        lines.append(f"Unallocated income: SGD {analysis['unallocated']:,.2f}.")
    lines.extend(analysis.get("warnings", []))
    lines.extend(draft.questions)
    lines.append(
        "The backend must validate the full plan and present exact changes for confirmation before saving."
    )
    return " ".join(lines)
