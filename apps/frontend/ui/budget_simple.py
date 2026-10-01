"""Everyday budget actions share the existing read-only and confirmed-write APIs."""

import json
from copy import deepcopy
from hashlib import sha256

import streamlit as st

from ui.components import backend_call, money
from ui.state import shift_month


def render_change(client, user_id, period, categories, planning, scope, draft_key):
    st.subheader("Explore a change", anchor=False)
    if not planning:
        st.caption(
            "Include take-home income and savings above to compare a change. Category limits can still be saved on their own."
        )
        return
    change = st.selectbox(
        "What would you like to change?",
        ["Choose a change", "Savings", "Take-home income", "A category amount"],
        key=scope + "-change",
    )
    if change == "Choose a change":
        return
    field = {"Savings": "savings_target", "Take-home income": "take_home_income"}.get(change)
    category = None
    if field:
        current = planning.get(field)
        label = (
            "New monthly savings (SGD)"
            if field == "savings_target"
            else "New monthly take-home income (SGD)"
        )
    else:
        if not categories:
            st.info("Add a category first.")
            return
        category = st.selectbox(
            "Category to change", list(categories), key=scope + "-change-category"
        )
        current, label = categories[category], "New category amount (SGD)"
    changed = st.number_input(
        label,
        min_value=0.0,
        value=float(current) if current is not None else None,
        key=scope + "-change-amount-" + (field or category),
    )
    scenario = (
        {"name": "Proposed change", field: changed}
        if field
        else {
            "name": "Proposed change",
            "categories": [{"category": category, "limit_amount": changed}],
        }
    )
    payload = {
        "period_start": str(period),
        "currency": "SGD",
        "action": "compare",
        "categories": [{"category": k, "limit_amount": v} for k, v in categories.items()],
        "planning": {
            **{
                k: v
                for k, v in planning.items()
                if k in {"take_home_income", "income_basis", "savings_target", "method"}
            },
            "expenses_confirmed": False,
        },
        "scenarios": [scenario],
    }
    signature = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    key = scope + "-simple-comparison"
    if st.button("Check this change", key=key + "-check"):
        result = backend_call(lambda: client.compare_budget(user_id, payload))
        if result is not None:
            st.session_state[key] = (signature, result)
    stored = st.session_state.get(key)
    if not stored or stored[0] != signature:
        return
    results = stored[1].get("results", [])
    if len(results) < 2:
        for question in stored[1].get("questions", []):
            st.info(question)
        return
    candidate = results[1]
    totals = candidate.get("totals")
    if totals:
        if totals["funding_gap"]:
            st.warning(
                f"This change leaves a shortfall of {money(totals['funding_gap'])}. Choose an amount to revise before saving."
            )
        elif candidate.get("meets_saved_constraints", True):
            st.success(
                f"This change leaves {money(totals['unallocated'])} unallocated after expenses and savings."
            )
        else:
            st.warning(
                "This change fits monthly income but conflicts with a saved fixed amount or savings allocation. Review the details below."
            )
        st.caption(
            "Monthly affordability uses the amounts supplied. Cash availability before payday is a separate check."
        )
    for question in candidate.get("questions", []):
        st.caption(question)
    if st.button("Review this change in my plan", key=key + "-adopt", disabled=totals is None):
        draft = deepcopy(candidate["draft"])
        draft["planning"].update(income_basis="unknown", expenses_confirmed=False)
        st.session_state[draft_key] = draft
        st.rerun()


def render_copy_month(client, user_id, period, budget):
    if not budget or not budget.get("planning"):
        return
    key = f"copy-month-{user_id}-{period}"
    target = shift_month(period, 1)
    if st.button("Use this plan next month", key=key + "-open"):
        st.session_state[key + "-expanded"] = True
        st.session_state[key + "-existing"] = backend_call(
            lambda: client.get_budget(user_id, target)
        )
    if not st.session_state.get(key + "-expanded"):
        return
    st.write(f"Prepare {target:%B %Y} using the saved category limits for {period:%B %Y}.")
    income = st.number_input(
        "Next month's take-home income (SGD)",
        min_value=0.0,
        value=float(budget["planning"]["take_home_income"]),
        key=key + "-income",
    )
    savings = st.number_input(
        "Next month's savings (SGD)",
        min_value=0.0,
        value=float(budget["planning"]["savings_target"]),
        key=key + "-savings",
    )
    overwrite = False
    if st.session_state.get(key + "-existing"):
        overwrite = st.checkbox(f"Replace my existing {target:%B %Y} plan", key=key + "-replace")
    payload = {
        "source_period": str(period),
        "first_period": str(target),
        "months": 1,
        "take_home_income": income,
        "savings_target": savings,
        "carry_rule": "copy_limits",
        "allow_overwrite": overwrite,
    }
    signature = json.dumps(payload, sort_keys=True)
    if st.button("Preview next month's plan", key=key + "-preview"):
        preview = backend_call(lambda: client.preview_budget_months(user_id, payload))
        if preview is not None:
            st.session_state[key + "-pending"] = (signature, preview)
    pending = st.session_state.get(key + "-pending")
    if not pending or pending[0] != signature:
        return
    preview = pending[1]
    for question in preview.get("questions", []) + preview.get("warnings", []):
        st.info(question)
    for item in preview.get("plans", []):
        st.table(
            [
                {"Category": c["category"], "Amount": money(c["limit_amount"])}
                for c in item["budget"]["categories"]
            ]
        )
        st.write(
            f"Expenses {money(item['expenses'])} · savings {money(savings)} · income {money(income)}"
        )
    approved = st.checkbox(
        f"These are my actual income, savings and complete expense limits for {target:%B %Y}.",
        key=key + "-approved",
    )
    if st.button(
        "Confirm next month's plan",
        key=key + "-confirm",
        disabled=not preview["ready"] or not approved,
    ):
        saved = backend_call(lambda: client.confirm_budget_months(user_id, preview["preview_id"]))
        if saved:
            st.session_state.pop(key + "-pending", None)
            st.session_state.pop(key + "-expanded", None)
            st.success(f"Saved your {target:%B %Y} plan.")
