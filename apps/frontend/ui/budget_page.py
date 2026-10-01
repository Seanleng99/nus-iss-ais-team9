"""Everyday budget monitoring and an explicit, cancellable monthly editor."""

import json
from hashlib import sha256

import streamlit as st

from ui.budget_editor import (
    render_category_rows,
    render_plan_summary,
    render_save_review,
    save_budget_with_feedback,
)
from ui.budget_methods import DESCRIPTIONS, render_method_choice, render_method_guide
from ui.budget_spending import render_spending
from ui.components import backend_call, money, page_header
from ui.styles import BUDGET_CSS


def render_budget_page(client, user_id, period, category_options, create_pie_chart):
    st.markdown(BUDGET_CSS, unsafe_allow_html=True)
    base = f"budget-{user_id}-{period.isoformat()}"
    draft_key = f"budget-edit-draft-{user_id}-{period.isoformat()}"
    budget = backend_call(lambda: client.get_budget(user_id, period))
    currency = (budget or {}).get("currency", "SGD")
    page_header("Budget", period.strftime("%B %Y"))
    feedback = st.session_state.get(base + "-saved-feedback")
    if feedback:
        st.success(feedback)

    def close_editor():
        for key in list(st.session_state):
            if key.startswith(base + "-editor-"):
                del st.session_state[key]
        st.session_state.pop(draft_key, None)
        st.session_state[base + "-editing"] = False

    draft = st.session_state.get(draft_key)
    editing = not budget or bool(draft) or st.session_state.get(base + "-editing", False)
    if budget and not editing and st.button("Edit budget", icon=":material/edit:"):
        st.session_state[base + "-editing"] = True
        st.rerun()
    if budget and not editing:
        render_spending(budget, currency, base, create_pie_chart)
    elif not budget:
        st.info(
            "Create your budget for this month. Enter your own amounts, then review and confirm before saving."
        )

    existing = {
        r["category"]: float(r["limit_amount"]) for r in (budget or {}).get("categories", [])
    }
    planning = (budget or {}).get("planning")
    if editing:
        st.subheader("Edit budget" if budget else "Create your budget", anchor=False)
        status = st.empty()
        if draft:
            existing = {
                r["category"]: float(r["limit_amount"]) if r["limit_amount"] is not None else None
                for r in draft["categories"]
            }
            planning = draft.get("planning")
        revision = sha256(json.dumps([existing, planning], sort_keys=True).encode()).hexdigest()[
            :12
        ]
        scope = base + "-editor-" + revision
        with st.container(border=True):
            summary = st.container(key="budget-plan-summary")
            edited_planning = None
            questions = []
            include_planning = currency == "SGD" and st.checkbox(
                "Include take-home income and savings",
                value=bool(planning),
                disabled=bool(planning),
                key=scope + "-include-planning",
            )
            if include_planning:
                prior = planning or {}
                income_column, savings_column = st.columns(2)
                income = income_column.number_input(
                    "Monthly take-home income (SGD)",
                    min_value=0.0,
                    value=float(prior["take_home_income"])
                    if prior.get("take_home_income") is not None
                    else None,
                    step=100.0,
                    format="%.2f",
                    key=scope + "-plan-income",
                )
                savings = savings_column.number_input(
                    "Monthly savings allocation (SGD)",
                    min_value=0.0,
                    value=float(prior["savings_target"])
                    if prior.get("savings_target") is not None
                    else None,
                    step=50.0,
                    format="%.2f",
                    key=scope + "-plan-savings",
                )
                if income is None:
                    income_column.caption(
                        "Enter actual monthly take-home income, including 0 if applicable."
                    )
                if savings is None:
                    savings_column.caption(
                        "Enter a savings allocation, including 0 if that is your choice."
                    )
                method, questions = render_method_choice(prior.get("method"), scope)
                edited_planning = {k: v for k, v in prior.items() if k != "use_recorded_spending"}
                edited_planning.update(
                    method=method,
                    take_home_income=income,
                    savings_target=savings,
                    income_basis="take_home",
                    expenses_confirmed=True,
                )
            st.markdown("**Category limits**")
            categories_key = scope + "-category-list"
            if categories_key not in st.session_state:
                st.session_state[categories_key] = (
                    list(existing)
                    if budget or draft
                    else ["housing", "food", "transport", "utilities"]
                )
            categories = st.session_state[categories_key]

            def remove_category(category):
                st.session_state[categories_key] = [
                    c for c in st.session_state[categories_key] if c != category
                ]

            values, group_questions = render_category_rows(
                categories,
                existing,
                (planning or {}).get("method"),
                edited_planning["method"] if edited_planning else None,
                currency,
                scope,
                on_remove=remove_category,
            )
            questions.extend(group_questions)
            _render_add_category(category_options, scope, categories_key)
            with summary:
                balance = render_plan_summary(values, edited_planning, currency)
            if edited_planning:
                with st.expander("How this method works", icon=":material/info:"):
                    st.caption(DESCRIPTIONS[method["name"]])
                    render_method_guide(method, income, savings, values, scope=scope)
                if method["name"] == "zero_based" and balance is not None and balance != 0:
                    questions.append(
                        "Assign all income to expenses or savings before saving a zero-based plan."
                    )
            payload = {
                "period_start": period.isoformat(),
                "currency": currency,
                "review_evidence": draft.get("review_evidence") if draft else None,
                "planning": edited_planning,
                "categories": [{"category": c, "limit_amount": v} for c, v in values.items()],
            }
            changed = render_save_review(budget, values, edited_planning, currency)
            if changed or draft:
                status.info("Unsaved changes — recorded spending still uses your saved budget.")
            else:
                status.caption("Editing your saved budget. No amounts have changed.")
            signature = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]
            confirmation_key = scope + "-confirmed-" + signature
            if st.session_state.pop(scope + "-rejected-confirmation", None) == confirmation_key:
                st.session_state[confirmation_key] = False
            approved = st.checkbox(
                "This is my actual take-home income and these limits include all my expenses."
                if edited_planning
                else f"I have reviewed these category limits for {period:%B %Y}.",
                key=confirmation_key,
            )
            if not values:
                questions.append("Add at least one category and enter its limit before saving.")
            if any(v is None for v in values.values()):
                questions.append("Enter every category limit, including 0 if that is your choice.")
            if edited_planning and (income is None or savings is None):
                questions.append("Enter take-home income and savings before saving.")
            if balance is not None and balance < 0:
                questions.append(f"Resolve the shortfall of {money(-balance)} before saving.")
            if budget and not changed and not draft:
                questions.append("No changes to save.")
            for question in dict.fromkeys(questions):
                st.caption(question)
            if not questions and not approved:
                st.caption("Review the changes and confirm the plan above before saving.")
            if st.button(
                "Save budget", type="primary", icon=":material/save:", disabled=bool(questions)
            ):
                if not approved:
                    st.warning("Review the changes and confirm the plan before saving.")
                else:
                    result = save_budget_with_feedback(client, user_id, payload)
                    if result:
                        close_editor()
                        st.session_state[base + "-saved-feedback"] = (
                            f"Budget saved for {period:%B %Y}."
                        )
                        st.rerun()
                    else:
                        st.session_state[scope + "-rejected-confirmation"] = confirmation_key
            st.button("Cancel changes", key=scope + "-cancel", on_click=close_editor)
    if budget and editing:
        render_spending(budget, currency, base, create_pie_chart)
    if currency == "SGD":
        st.caption(
            "Ask Coach to compare changes to your saved plan, savings amounts or category limits. "
            "Manage savings targets on the Goals page."
        )


def _render_add_category(options, scope, categories_key):
    categories = st.session_state[categories_key]
    choice_key, name_key, error_key = (
        scope + suffix for suffix in ("-add-choice", "-add-name", "-add-error")
    )
    choices = [c for c in options if c not in categories]
    choice = st.selectbox(
        "Category to add",
        [*choices, "Custom category"],
        index=None,
        format_func=str.title,
        placeholder="Choose a category or Custom category",
        key=choice_key,
    )
    if choice == "Custom category":
        st.text_input("Custom category name", max_chars=64, key=name_key)

    def add():
        value = (
            st.session_state.get(name_key, "")
            if st.session_state[choice_key] == "Custom category"
            else st.session_state[choice_key]
        )
        name = " ".join((value or "").split()).lower()
        if not name or len(name) > 64:
            st.session_state[error_key] = "Enter a category name with 1 to 64 characters."
        elif name in st.session_state[categories_key]:
            st.session_state[error_key] = (
                "That category is already in your plan. Edit its limit above."
            )
        elif len(st.session_state[categories_key]) >= 50:
            st.session_state[error_key] = (
                "A budget can contain up to 50 categories. Remove one before adding another."
            )
        else:
            st.session_state[categories_key] = [*st.session_state[categories_key], name]
            st.session_state[choice_key] = None
            st.session_state[name_key] = ""
            st.session_state.pop(error_key, None)

    st.button(
        "Add category",
        key=scope + "-add",
        disabled=choice is None or len(categories) >= 50,
        icon=":material/add:",
        on_click=add,
    )
    if len(categories) >= 50:
        st.caption("50-category limit reached. Remove a category before adding another.")
    if st.session_state.get(error_key):
        st.warning(st.session_state[error_key])
