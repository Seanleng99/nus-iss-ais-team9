"""A single method choice in the monthly editor; amounts remain user-controlled."""

from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import streamlit as st

from ui.components import money

METHODS = {
    "flexible": "Flexible category plan",
    "50_30_20": "50/30/20",
    "80_20": "80/20",
    "zero_based": "Zero-based",
    "pay_yourself_first": "Savings first",
    "custom": "Custom percentages",
}

DESCRIPTIONS = {
    "flexible": "Choose your own category limits and savings. Some income can stay unallocated.",
    "50_30_20": "Use 50% for needs, 30% for wants and 20% for savings as a guide.",
    "80_20": "Use 80% for expenses and 20% for savings as a guide. No category grouping is needed.",
    "zero_based": "Give every dollar a purpose: expenses plus savings must equal take-home income.",
    "pay_yourself_first": "Choose your savings amount first, then fit expenses into the income left over.",
    "custom": "Choose your own needs, wants and savings percentages, totaling 100%.",
}


def render_method_choice(prior, scope):
    prior = prior or {}
    choices = list(METHODS)
    chosen = st.selectbox(
        "Budgeting method", choices, format_func=METHODS.get,
        index=choices.index(prior.get("name", "flexible")), key=scope + "-method",
    )
    st.caption(DESCRIPTIONS[chosen])
    method = {"name": chosen, "category_groups": {}}
    questions = []
    if chosen == "custom":
        columns = st.columns(3)
        saved = prior.get("percentages") or {}
        percentages = {
            group: columns[index].number_input(
                f"{group.title()} (%)", min_value=0.0, max_value=100.0,
                value=float(saved[group]) if saved.get(group) is not None else None,
                step=1.0, format="%.2f", key=f"{scope}-{group}-percentage",
            )
            for index, group in enumerate(("needs", "wants", "savings"))
        }
        if any(value is None for value in percentages.values()):
            questions.append("Enter all three percentages, including 0 if that is your choice.")
        else:
            method["percentages"] = percentages
            total = sum(Decimal(str(value)) for value in percentages.values())
            st.caption(f"Percentage total: {total:g}% of take-home income.")
            if total != 100:
                questions.append("Adjust the percentages so they total 100%.")
    for question in questions:
        st.caption(question)
    return method, questions


def render_method_guide(method, income, savings, categories, *, scope=None):
    """Display indicative targets, never fill or save amounts."""
    if income is None:
        return
    income = Decimal(str(income))
    name = method["name"]
    percentages = {"needs": 50, "wants": 30, "savings": 20} if name == "50_30_20" else method.get("percentages")
    if name == "custom" and (not percentages or sum(Decimal(str(v)) for v in percentages.values()) != 100):
        return
    if percentages:
        needs = (income * Decimal(str(percentages["needs"])) / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        wants = min(
            (income * Decimal(str(percentages["wants"])) / 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            ), income - needs,
        )
        targets = {"needs": needs, "wants": wants, "savings": income - needs - wants}
        st.caption("Monthly guide: " + " · ".join(f"{g.title()} {money(v)}" for g, v in targets.items()))
        complete = all(c in method["category_groups"] and v is not None for c, v in categories.items())
        actual = {
            group: sum(Decimal(str(v)) for c, v in categories.items() if method["category_groups"].get(c) == group) if complete else None
            for group in ("needs", "wants")
        }
        actual["savings"] = savings
        render_targets(targets, actual)
        st.caption("These targets are guidance. Your entered amounts stay unchanged.")
        suggest_savings(targets["savings"], scope)
    elif name == "80_20":
        target = (income * Decimal("0.20")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        st.caption(f"Monthly guide: expenses {money(income - target)} · savings {money(target)}. Your entered amounts stay unchanged.")
        expenses = sum(Decimal(str(v)) for v in categories.values()) if all(v is not None for v in categories.values()) else None
        render_targets({"expenses": income - target, "savings": target}, {"expenses": expenses, "savings": savings})
        suggest_savings(target, scope)
    elif name == "pay_yourself_first" and savings is not None:
        st.caption(f"After your savings allocation, {money(income - Decimal(str(savings)))} is available for expenses.")


def render_targets(targets, actual):
    st.table(pd.DataFrame([
        {"Group": group.title(), "Suggested": money(target), "Your plan": money(actual[group]) if actual[group] is not None else "Needs input"}
        for group, target in targets.items()
    ]))


def suggest_savings(target, scope):
    if not scope:
        return

    def apply():
        st.session_state[f"{scope}-plan-savings"] = float(target)

    st.button("Use suggested savings amount", key=scope + "-suggest-savings", on_click=apply)
    st.caption("This fills the savings field only. Review the plan and confirm before saving.")
