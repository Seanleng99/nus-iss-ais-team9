"""Everyday budget actions share the existing read-only and confirmed-write APIs."""

import json
from copy import deepcopy
from hashlib import sha256

import pandas as pd
import streamlit as st

from ui.components import backend_call, money


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
        before = results[0]
        before_totals = before.get("totals")
        if before_totals:
            def amount(result, field):
                value = result["draft"]["planning"].get(field)
                return money(value) if value is not None else "Not entered"

            rows = [
                {"Item": label, "Current": amount(before, field), "Proposed": amount(candidate, field)}
                for field, label in (("take_home_income", "Income"), ("savings_target", "Savings"))
            ]
            for label, field in (("Expenses", "expense_total"), ("Left to allocate", "unallocated"), ("Shortfall", "funding_gap")):
                rows.append({"Item": label, "Current": money(before_totals[field]), "Proposed": money(totals[field])})
            if category:
                proposed = next((c["limit_amount"] for c in candidate["draft"]["categories"] if c["category"] == category), None)
                rows.insert(0, {"Item": category.title(), "Current": money(current) if current is not None else "Not entered", "Proposed": money(proposed) if proposed is not None else "Not entered"})
            st.table(pd.DataFrame(rows))
            st.caption("Current uses the editor amounts. Adopting a change fills the editor; it does not save it.")
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
