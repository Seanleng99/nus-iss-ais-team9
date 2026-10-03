"""Readable category rows, live totals and review of the exact plan being saved."""
from decimal import Decimal

import httpx
import pandas as pd
import streamlit as st

from ui.budget_methods import METHODS
from ui.components import backend_call, money
from ui.i18n import display_frame, option_formatter, option_label, ui_text


def render_category_rows(categories, existing, prior_method, method, currency, scope, *, on_remove=None):
    values = {}
    grouping = method and method["name"] in {"50_30_20", "custom"}
    saved_groups = (prior_method or {}).get("category_groups") or {}
    if grouping:
        st.caption(ui_text('Choose Needs for essential costs or Wants for optional spending in each row.'))
    for category in categories:
        with st.container():
            columns = st.columns([3, 2]) if grouping else [st.container()]
            values[category] = columns[0].number_input(
                f"{option_label(category)} ({currency})", min_value=0.0,
                value=existing.get(category), step=25.0, format="%.2f",
                key=f"{scope}-{category}-v3",
            )
            if values[category] is None:
                columns[0].caption(ui_text('Enter a monthly limit for {v0}, including 0 if that is your choice.', v0=option_label(category)))
            if grouping:
                selected = columns[1].selectbox(
                    ui_text('Type for {v0}', v0=option_label(category)), ["needs", "wants"],
                    index=["needs", "wants"].index(saved_groups[category])
                    if category in saved_groups else None,
                    format_func=option_formatter(), placeholder=ui_text('Choose type'),
                    key=f"{scope}-{category}-group",
                )
                if selected:
                    method["category_groups"][category] = selected
                else:
                    columns[1].caption(ui_text('Choose Needs or Wants for this category.'))
            if on_remove:
                st.button(ui_text('Remove {v0}', v0=option_label(category)), key=f"{scope}-{category}-remove",
                          icon=":material/remove:", on_click=on_remove, args=(category,),
                          help=ui_text('Remove this category limit from the unsaved plan. Recorded transactions are kept.'))
    missing = [c for c in categories if grouping and c not in method["category_groups"]]
    questions = [ui_text("Choose Needs or Wants for: {categories}.", categories=", ".join(option_label(c) for c in missing))] if missing else []
    for question in questions:
        st.caption(ui_text(question))
    return values, questions


def render_plan_summary(values, planning, currency):
    expenses = sum((Decimal(str(v)) for v in values.values()), Decimal(0)) if all(v is not None for v in values.values()) else None
    if not planning:
        st.metric(ui_text('Expenses'), money(expenses, currency) if expenses is not None else ui_text("Enter category amounts"))
        return None
    income, savings = planning["take_home_income"], planning["savings_target"]
    balance = Decimal(str(income)) - expenses - Decimal(str(savings)) if None not in (income, expenses, savings) else None
    columns = st.columns(4)
    for column, label, amount in zip(columns[:3], ("Income", "Expenses", "Savings"), (income, expenses, savings), strict=True):
        column.metric(ui_text(label), money(amount, currency) if amount is not None else ui_text("Not entered"))
    columns[3].metric(
        ui_text('Shortfall') if balance is not None and balance < 0 else ui_text('Left to allocate'),
        money(abs(balance), currency) if balance is not None else ui_text("Enter missing amounts"),
    )
    if balance is not None and balance < 0:
        st.warning(ui_text('Expenses and savings exceed income by {v0}. Reduce an amount or revise income before saving.', v0=money(-balance, currency)))
    st.caption(ui_text('These are your plan amounts. Left to allocate is income not yet assigned, not a bank balance.'))
    return balance


def render_save_review(budget, values, planning, currency):
    old_categories = {c["category"]: c["limit_amount"] for c in (budget or {}).get("categories", [])}
    old_plan = (budget or {}).get("planning") or {}
    changes = []
    for category in dict.fromkeys([*old_categories, *values]):
        current = old_categories.get(category)
        proposed = values.get(category)
        if category not in old_categories or category not in values or current != proposed:
            changes.append({
                "Change": option_label(category),
                "Saved": money(current, currency) if current is not None else ui_text("Not set"),
                "This plan": ui_text("Remove limit") if category not in values else money(proposed, currency) if proposed is not None else ui_text("Enter amount"),
            })
    if planning:
        for field, label in (("take_home_income", "Income"), ("savings_target", "Savings")):
            before, after = old_plan.get(field), planning[field]
            if before != after or not old_plan:
                changes.append({"Change": ui_text(label), "Saved": money(before, currency) if before is not None else ui_text("Not set"), "This plan": money(after, currency) if after is not None else ui_text("Enter amount")})
        old_method = old_plan.get("method") or {"name": "flexible", "category_groups": {}}
        method = planning["method"]
        if old_method["name"] != method["name"] or not old_plan:
            changes.append({"Change": ui_text("Budgeting method"), "Saved": ui_text(METHODS[old_method["name"]]) if old_plan else ui_text("Not set"), "This plan": ui_text(METHODS[method["name"]])})
        if method["name"] == "custom" and method.get("percentages"):
            for group, value in method["percentages"].items():
                before = (old_method.get("percentages") or {}).get(group)
                if value != before:
                    changes.append({"Change": ui_text("{group} percentage", group=option_label(group)), "Saved": f"{before:g}%" if before is not None else ui_text("Not set"), "This plan": f"{value:g}%"})
        if old_method.get("category_groups") != method["category_groups"]:
            for category, group in method["category_groups"].items():
                if old_method.get("category_groups", {}).get(category) != group:
                    changes.append({"Change": ui_text("{category} type", category=option_label(category)), "Saved": option_label(old_method.get("category_groups", {}).get(category, "Not set")), "This plan": option_label(group)})
    st.markdown(ui_text('**Review before saving**'))
    if changes:
        st.table(display_frame(pd.DataFrame(changes[:6])))
        if len(changes) > 6:
            with st.expander(ui_text('Review all {v0} changes', v0=len(changes))):
                st.table(display_frame(pd.DataFrame(changes)))
    else:
        st.caption(ui_text('The entered amounts and method match your saved plan.'))
    if any(c not in values for c in old_categories):
        st.caption(ui_text('Removing a limit keeps recorded transactions. Those expenses will appear as unbudgeted spending.'))
    return bool(changes)


def save_budget_with_feedback(client, user_id, payload):
    def save():
        try:
            return client.save_budget(user_id, payload)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 422:
                raise
            try:
                detail = error.response.json().get("detail")
            except (ValueError, AttributeError):
                detail = None
            messages = []
            if isinstance(detail, list):
                for item in detail:
                    if not isinstance(item, dict) or not isinstance(item.get("msg"), str):
                        continue
                    path = item.get("loc", [])
                    label = ""
                    if "categories" in path:
                        position = path.index("categories") + 1
                        if position < len(path) and isinstance(path[position], int) and 0 <= path[position] < len(payload["categories"]):
                            label = payload["categories"][path[position]]["category"].title() + ": "
                    elif path and path[-1] in {"take_home_income", "savings_target", "needs", "wants", "savings"}:
                        label = str(path[-1]).replace("_", " ").title() + ": "
                    messages.append(label + item["msg"].removeprefix("Value error, "))
            elif isinstance(detail, str):
                messages.append(detail)
            if not messages:
                messages.append("The plan needs correction. Check category amounts, income, savings and the selected method.")
            for message in dict.fromkeys(m for m in messages if isinstance(m, str) and m):
                st.warning(message.removeprefix("Value error, "))
            st.info(ui_text('Your inputs are still here. Revise the plan and confirm again before saving.'))
            return None
    return backend_call(save)
