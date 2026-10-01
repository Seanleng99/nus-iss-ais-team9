"""Everyday budget actions share the existing read-only and confirmed-write APIs."""

import json
from copy import deepcopy
from hashlib import sha256

import streamlit as st

from ui.components import backend_call, money
from ui.state import shift_month


def confirm_preview(client, user_id, key, pending):
    """Use the authoritative preview, not values edited after it was produced."""
    st.caption("Review these changes. Nothing has been saved.")
    if st.button("Confirm changes", key=key + "-confirm"):
        result = backend_call(
            lambda: client.confirm_workspace_change(user_id, pending["preview_id"])
        )
        if result is not None:
            st.session_state.pop(key + "-pending", None)
            st.session_state.pop(key, None)
            st.session_state[key + "-reset"] = True
            st.success("Changes saved.")
            st.rerun()


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


def render_fixed_amounts(client, user_id, period, categories):
    key = f"fixed-amounts-{user_id}-{period}"
    if key not in st.session_state:
        data = backend_call(lambda: client.get_budget_commitments(user_id, period))
        if data is None:
            return
        st.session_state[key] = data
    policy = st.session_state[key].get("policy") or {}
    selected = st.multiselect(
        "Keep these category amounts fixed",
        list(dict.fromkeys([*categories, *policy.get("protected_categories", [])])),
        default=policy.get("protected_categories", []),
        key=key + "-selected",
    )
    st.caption(
        "Coach will keep these amounts when exploring reductions. Other saved minimums and obligations remain in force."
    )
    payload = {"period_start": str(period), "protected_categories": selected}
    signature = json.dumps(payload, sort_keys=True)
    if st.button("Preview fixed amounts", key=key + "-preview"):
        result = backend_call(
            lambda: client.preview_workspace_change(user_id, "commitments", payload)
        )
        if result:
            st.session_state[key + "-pending"] = (signature, result)
    pending = st.session_state.get(key + "-pending")
    if pending and pending[0] == signature:
        st.write(
            "Fixed categories: "
            + (", ".join(pending[1]["target"]["protected_categories"]) or "none selected")
        )
        st.table(
            [
                {"Category": category, "Fixed amount": money(categories[category])}
                for category in pending[1]["target"]["protected_categories"]
                if category in categories
            ]
        )
        confirm_preview(client, user_id, key, pending[1])


def render_goal_allocation(client, user_id, period):
    key = f"simple-goal-{user_id}-{period}"
    stored = backend_call(lambda: client.get_budget_commitments(user_id, period))
    goals = backend_call(lambda: client.list_goals(user_id))
    if stored is None or goals is None:
        return
    choices = {g["id"]: g for g in goals if g["target_amount"]["currency"] == "SGD"}
    if not choices:
        st.info("Create a savings goal in Goals first, then choose its monthly contribution here.")
        return
    selected = st.selectbox(
        "Savings goal",
        list(choices),
        format_func=lambda identifier: choices[identifier]["name"],
        key=key + "-goal",
    )
    prior = next(
        (g for g in (stored.get("policy") or {}).get("goals", []) if g["goal_id"] == selected), None
    )
    remove = bool(prior) and st.checkbox(
        "Stop allocating savings to this goal", key=key + "-remove-" + selected
    )
    amount = (
        None
        if remove
        else st.number_input(
            "Monthly amount from my savings (SGD)",
            min_value=0.0,
            value=float(prior["monthly_amount"]) if prior else None,
            key=key + "-amount-" + selected,
        )
    )
    st.caption(
        "Goal contributions and upcoming-expense reserves share the plan's savings allocation; they do not add another expense or move money."
    )
    payload = {
        "period_start": str(period),
        "edits": [
            {
                "collection": "goals",
                "key": selected,
                "action": "remove" if remove else "update" if prior else "add",
                "values": {} if remove else {"monthly_amount": amount},
            }
        ],
    }
    signature = json.dumps(payload, sort_keys=True)
    if st.button("Preview goal contribution", key=key + "-preview"):
        if amount is None and not remove:
            st.warning("Choose a monthly contribution, including 0 if that is your choice.")
        else:
            pending = backend_call(
                lambda: client.preview_workspace_change(user_id, "commitments", payload)
            )
            if pending:
                st.session_state[key + "-pending"] = (signature, pending)
    pending = st.session_state.get(key + "-pending")
    if pending and pending[0] == signature:
        st.write(
            f"Stop funding {choices[selected]['name']}."
            if remove
            else f"Allocate {money(amount)} of monthly savings to {choices[selected]['name']}."
        )
        confirm_preview(client, user_id, key, pending[1])


def render_upcoming_expense(client, user_id, period):
    from datetime import date

    key = f"upcoming-expense-{user_id}-{period}"
    if st.session_state.pop(key + "-reset", False):
        for widget_key in list(st.session_state):
            if widget_key.startswith(key + "-"):
                st.session_state.pop(widget_key, None)
    data = backend_call(lambda: client.get_budget_workspace(user_id))
    if data is None:
        return
    reserves = (data["settings"].get("reserves") or {}).get("reserves", [])
    choices = {r["id"]: r for r in reserves}
    selected = st.selectbox(
        "Upcoming expense",
        ["new", *choices],
        format_func=lambda identifier: (
            "Add an upcoming expense" if identifier == "new" else choices[identifier]["name"]
        ),
        key=key + "-expense",
    )
    previous = choices.get(selected) or {}
    remove = bool(previous) and st.checkbox(
        "Remove this expense reserve", key=key + "-remove-" + selected
    )
    name = st.text_input(
        "Expense name", value=previous.get("name", ""), key=key + "-name-" + selected
    )
    target = st.number_input(
        "Amount needed (SGD)",
        min_value=0.0,
        value=float(previous["target_amount"]) if previous else None,
        key=key + "-target-" + selected,
    )
    reserved = st.number_input(
        "Already set aside (SGD)",
        min_value=0.0,
        value=float(previous["current_reserved"]) if previous else None,
        key=key + "-reserved-" + selected,
    )
    due = st.date_input(
        "Needed by",
        value=date.fromisoformat(previous["due_on"]) if previous else None,
        key=key + "-due-" + selected,
    )
    contribution = st.number_input(
        "Monthly amount from savings (SGD)",
        min_value=0.0,
        value=float(previous["monthly_contribution"]) if previous else None,
        key=key + "-amount-" + selected,
    )
    start = st.date_input(
        "Start saving in month",
        value=date.fromisoformat(previous["start_period"]) if previous else period,
        key=key + "-start-" + selected,
    ).replace(day=1)
    if target is not None and reserved is not None and due and due >= start:
        from decimal import ROUND_CEILING, Decimal

        months = (due.year - start.year) * 12 + due.month - start.month + 1
        suggested = (
            max(Decimal(str(target)) - Decimal(str(reserved)), Decimal(0)) / months
        ).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
        st.caption(
            f"Suggested monthly amount: {money(float(suggested))}, including a contribution before the due date in the final month. Choose the amount to allocate above."
        )
    st.caption(
        "This reserve shares your savings allocation with other reserves and goals. No money is moved."
    )
    values = {
        "name": name,
        "target_amount": target,
        "current_reserved": reserved,
        "monthly_contribution": contribution,
        "start_period": str(start),
        "due_on": str(due) if due else None,
    }
    edit = {
        "collection": "reserves",
        "action": "remove" if remove else "update" if previous else "add",
        "values": {} if remove else values,
    }
    if previous:
        edit["key"] = selected
    payload = {"edits": [edit]}
    signature = json.dumps(payload, sort_keys=True)
    if st.button("Preview upcoming expense", key=key + "-preview"):
        if not remove and (
            not name.strip() or any(v is None for v in [target, reserved, contribution, due])
        ):
            st.warning(
                "Supply the expense name, amounts and due date, including 0 for nothing already set aside."
            )
        else:
            pending = backend_call(
                lambda: client.preview_workspace_change(user_id, "reserves", payload)
            )
            if pending:
                st.session_state[key + "-pending"] = (signature, pending)
    pending = st.session_state.get(key + "-pending")
    if pending and pending[0] == signature:
        st.write(
            f"Remove the reserve for {name}."
            if remove
            else f"Set aside {money(contribution)}/month for {name}, target {money(target)}, already reserved {money(reserved)}, from {start:%B %Y}, due {due}."
        )
        confirm_preview(client, user_id, key, pending[1])


def render_payday(client, user_id, period):
    """Add one bill/payday at a time; preserve all existing schedules and links."""
    key = f"simple-payday-{user_id}"
    if st.session_state.pop(key + "-reset", False):
        for suffix in ["kind", "name", "amount", "category", "due", "frequency", "result"]:
            st.session_state.pop(key + "-" + suffix, None)
    saved = backend_call(lambda: client.get_cashflow_settings(user_id))
    if saved is None:
        saved = {}
    if saved:
        st.caption(
            f"Using your saved opening balance of {money(saved['opening_balance'])} on {saved['opening_on']}."
        )
        st.table(
            [
                {
                    "Bill or payday": s["name"],
                    "Amount": money(s["amount"]),
                    "Frequency": s["frequency"],
                    "First date": s["first_on"],
                }
                for s in saved["schedules"]
            ]
        )
    else:
        st.caption(
            "Start with available cash and its date, then add a bill or payday. A monthly budget alone cannot establish your available cash."
        )
    from datetime import date

    opening = st.date_input(
        "Available cash date",
        value=date.fromisoformat(saved["opening_on"]) if saved else None,
        key=key + "-date",
    )
    balance = st.number_input(
        "Available cash at the start of that date (SGD)",
        value=float(saved["opening_balance"]) if saved else None,
        key=key + "-balance",
    )
    kind = st.selectbox("Add a bill or payday", ["Choose", "Bill", "Payday"], key=key + "-kind")
    values = None
    if kind != "Choose":
        name = st.text_input("Name", key=key + "-name")
        amount = st.number_input("Amount (SGD)", min_value=0.01, value=None, key=key + "-amount")
        category = st.text_input("Category", key=key + "-category")
        due = st.date_input("First payment date", value=None, key=key + "-due")
        frequency = st.selectbox(
            "Repeat",
            ["Choose", "once", "weekly", "fortnightly", "monthly", "yearly"],
            key=key + "-frequency",
        )
        if (
            name.strip()
            and category.strip()
            and amount is not None
            and due
            and frequency != "Choose"
        ):
            values = {
                "name": name,
                "amount": amount,
                "category": category,
                "kind": "expense" if kind == "Bill" else "income",
                "first_on": str(due),
                "frequency": frequency,
            }
    payload = {
        "opening_on": str(opening) if opening else None,
        "opening_balance": balance,
        "currency": "SGD",
    }
    if values:
        payload["edits"] = [{"collection": "schedules", "action": "add", "values": values}]
    signature = json.dumps(payload, sort_keys=True)
    if st.button("Preview cash-flow changes", key=key + "-preview"):
        if (
            opening is None
            or balance is None
            or (kind != "Choose" and values is None)
            or (not saved and values is None)
        ):
            st.warning(
                "Supply the available cash date and amount, and complete the bill or payday details."
            )
        else:
            pending = backend_call(
                lambda: client.preview_workspace_change(user_id, "cashflow", payload)
            )
            if pending:
                st.session_state[key + "-pending"] = (signature, pending)
    pending = st.session_state.get(key + "-pending")
    if pending and pending[0] == signature:
        target = pending[1]["target"]
        st.write(f"Available cash {money(target['opening_balance'])} on {target['opening_on']}.")
        st.table(
            [
                {
                    "Bill or payday": s["name"],
                    "Amount": money(s["amount"]),
                    "First date": s["first_on"],
                    "Repeat": s["frequency"],
                }
                for s in target["schedules"]
            ]
        )
        confirm_preview(client, user_id, key, pending[1])
    if saved:
        through = st.date_input("Check through", value=None, key=key + "-through")
        evidence = json.dumps(saved, sort_keys=True)
        if st.button("Check available cash", key=key + "-calculate") and through:
            result = backend_call(lambda: client.get_cashflow(user_id, through))
            st.session_state[key + "-result"] = (str(through), evidence, result)
        stored = st.session_state.get(key + "-result")
        if stored and stored[0] == str(through) and stored[1] == evidence and stored[2]:
            result = stored[2]
            for warning in result.get("warnings", result.get("questions", [])):
                st.caption(warning)
            if not result.get("needs_input"):
                st.metric("Lowest projected available cash", money(result["lowest_balance"]))
                if result.get("first_shortfall_on"):
                    st.warning("Projected shortage from " + result["first_shortfall_on"])
                st.caption(
                    "This check covers recorded cash flows and scheduled bills/paydays. It does not include all remaining category allowances."
                )
                if result.get("days"):
                    import pandas as pd

                    st.line_chart(
                        pd.DataFrame(result["days"]).set_index("date")[
                            ["projected_closing_balance"]
                        ]
                    )
        if st.checkbox(
            "Include remaining category spending and savings timing", key=key + "-timing"
        ):
            from ui.budget_timing import render_timing

            render_timing(client, user_id, period)
        if st.checkbox("Match a recorded payment, income or refund", key=key + "-matching"):
            from ui.budget_reconciliation import render_reconciliation

            render_reconciliation(client, user_id)
