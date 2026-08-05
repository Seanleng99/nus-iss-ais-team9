from datetime import date

import pandas as pd
import streamlit as st

from client import build_request
from ui.components import backend_call, clamp_progress, money, page_header, percent
from ui.state import get_client, get_period_start, get_user_id, today_singapore

CATEGORIES = [
    "housing",
    "food",
    "transport",
    "utilities",
    "healthcare",
    "education",
    "entertainment",
    "shopping",
    "other",
]


def _category_label(category: str) -> str:
    return category.replace("_", " ").title()


def _transaction_payload(
    description: str,
    category: str,
    amount: float,
    occurred_on: date,
    recurring: bool,
) -> dict:
    return {
        "description": description.strip(),
        "category": category,
        "amount": {"currency": "SGD", "amount": amount},
        "occurred_on": occurred_on.isoformat(),
        "recurring": recurring,
    }


def dashboard_page() -> None:
    client = get_client()
    user_id = get_user_id()
    period_start = get_period_start()
    page_header("Overview", period_start.strftime("%B %Y"))
    dashboard = backend_call(lambda: client.get_dashboard(user_id, period_start))
    if not dashboard:
        st.info("Create a profile to start your financial workspace.")
        return

    currency = dashboard["currency"]
    income, spent = st.columns(2)
    income.metric("Monthly income", money(dashboard["monthly_income"], currency))
    spent.metric("Spent", money(dashboard["total_spent"], currency))
    balance, rate = st.columns(2)
    balance.metric("Available", money(dashboard["available_balance"], currency))
    rate.metric("Savings rate", percent(dashboard["savings_rate_percent"]))

    st.subheader("Spending")
    category_spending = dashboard.get("category_spending", {})
    if category_spending:
        spending_frame = pd.DataFrame(
            {
                "Category": [_category_label(name) for name in category_spending],
                "Amount": list(category_spending.values()),
            }
        ).set_index("Category")
        st.bar_chart(spending_frame, horizontal=True, color="#18794e")
    else:
        st.caption("No transactions recorded for this month.")

    budget = dashboard.get("budget")
    st.subheader("Budget")
    if budget:
        budget_columns = st.columns(3)
        budget_columns[0].metric("Planned", money(budget["total_limit"], currency))
        budget_columns[1].metric("Used", money(budget["total_spent"], currency))
        budget_columns[2].metric("Remaining", money(budget["total_remaining"], currency))
        if budget["total_limit"] > 0:
            st.progress(
                clamp_progress(budget["total_spent"] / budget["total_limit"]),
                text="Monthly budget used",
            )
    else:
        st.caption("No budget set for this month.")

    st.subheader("Goals")
    goals = dashboard.get("goals", [])
    if not goals:
        st.caption("No active goals.")
    for goal in goals:
        left, right = st.columns([3, 1])
        left.write(f"**{goal['name']}**")
        right.write(money(goal["current_amount"], currency))
        st.progress(
            clamp_progress(goal["progress_percent"] / 100),
            text=f"{goal['progress_percent']:.0f}% of {money(goal['target_amount'], currency)}",
        )


def transactions_page() -> None:
    client = get_client()
    user_id = get_user_id()
    period_start = get_period_start()
    page_header("Transactions", period_start.strftime("%B %Y"))
    transactions = backend_call(lambda: client.list_transactions(user_id, period_start)) or []
    ledger_tab, add_tab = st.tabs(["Ledger", "Add transaction"])

    with add_tab:
        with st.form("add-transaction", clear_on_submit=True):
            description = st.text_input("Description", max_chars=255)
            first, second = st.columns(2)
            category = first.selectbox(
                "Category", CATEGORIES, format_func=_category_label, key="add-category"
            )
            amount = second.number_input("Amount (SGD)", min_value=0.01, step=10.0)
            third, fourth = st.columns(2)
            occurred_on = third.date_input("Date", value=today_singapore())
            recurring = fourth.toggle("Recurring expense")
            add_submitted = st.form_submit_button(
                "Add transaction", type="primary", icon=":material/add:"
            )
        if add_submitted:
            if not description.strip():
                st.warning("Enter a transaction description.")
            else:
                result = backend_call(
                    lambda: client.create_transaction(
                        user_id,
                        _transaction_payload(
                            description, category, amount, occurred_on, recurring
                        ),
                    )
                )
                if result:
                    st.success("Transaction added.")
                    st.rerun()

    with ledger_tab:
        if not transactions:
            st.info("No transactions recorded for this month.")
            return
        frame = pd.DataFrame(
            [
                {
                    "Date": item["occurred_on"],
                    "Description": item["description"],
                    "Category": _category_label(item["category"]),
                    "Amount": item["amount"]["amount"],
                    "Recurring": item["recurring"],
                }
                for item in transactions
            ]
        )
        st.dataframe(
            frame,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Amount": st.column_config.NumberColumn("Amount (SGD)", format="%.2f"),
            },
        )

        st.subheader("Manage transaction")
        selected_id = st.selectbox(
            "Transaction",
            [item["id"] for item in transactions],
            format_func=lambda value: next(
                f"{item['occurred_on']} · {item['description']}"
                for item in transactions
                if item["id"] == value
            ),
        )
        selected = next(item for item in transactions if item["id"] == selected_id)
        selected_category = (
            selected["category"] if selected["category"] in CATEGORIES else "other"
        )
        with st.form("manage-transaction"):
            edit_description = st.text_input("Description", value=selected["description"])
            first, second = st.columns(2)
            edit_category = first.selectbox(
                "Category",
                CATEGORIES,
                index=CATEGORIES.index(selected_category),
                format_func=_category_label,
                key="edit-category",
            )
            edit_amount = second.number_input(
                "Amount (SGD)", min_value=0.01, value=float(selected["amount"]["amount"])
            )
            third, fourth = st.columns(2)
            edit_date = third.date_input(
                "Date", value=date.fromisoformat(selected["occurred_on"]), key="edit-date"
            )
            edit_recurring = fourth.toggle("Recurring expense", value=selected["recurring"])
            save, delete = st.columns(2)
            save_submitted = save.form_submit_button(
                "Save changes", type="primary", icon=":material/save:"
            )
            delete_submitted = delete.form_submit_button(
                "Delete", icon=":material/delete:"
            )
        if save_submitted:
            result = backend_call(
                lambda: client.update_transaction(
                    user_id,
                    selected_id,
                    _transaction_payload(
                        edit_description,
                        edit_category,
                        edit_amount,
                        edit_date,
                        edit_recurring,
                    ),
                )
            )
            if result:
                st.success("Transaction updated.")
                st.rerun()
        if delete_submitted:
            backend_call(lambda: client.delete_transaction(user_id, selected_id))
            st.success("Transaction deleted.")
            st.rerun()


def budget_page() -> None:
    client = get_client()
    user_id = get_user_id()
    period_start = get_period_start()
    page_header("Budget", period_start.strftime("%B %Y"))
    budget = backend_call(lambda: client.get_budget(user_id, period_start))
    existing = {
        item["category"]: float(item["limit_amount"])
        for item in (budget or {}).get("categories", [])
    }

    with st.form("monthly-budget"):
        values: dict[str, float] = {}
        columns = st.columns(3)
        for index, category in enumerate(CATEGORIES):
            values[category] = columns[index % 3].number_input(
                f"{_category_label(category)} (SGD)",
                min_value=0.0,
                value=existing.get(category, 0.0),
                step=25.0,
                key=f"budget-{category}",
            )
        budget_submitted = st.form_submit_button(
            "Save budget", type="primary", icon=":material/save:"
        )
    if budget_submitted:
        payload = {
            "period_start": period_start.isoformat(),
            "currency": "SGD",
            "categories": [
                {"category": category, "limit_amount": amount}
                for category, amount in values.items()
                if amount > 0
            ],
        }
        result = backend_call(lambda: client.save_budget(user_id, payload))
        if result:
            st.success("Budget saved.")
            st.rerun()

    if budget:
        st.subheader("Actual versus planned")
        comparison = pd.DataFrame(
            [
                {
                    "Category": _category_label(item["category"]),
                    "Planned": item["limit_amount"],
                    "Actual": item["spent_amount"],
                    "Remaining": item["remaining_amount"],
                }
                for item in budget["categories"]
            ]
        )
        st.dataframe(
            comparison,
            hide_index=True,
            use_container_width=True,
            column_config={
                name: st.column_config.NumberColumn(name, format="SGD %.2f")
                for name in ("Planned", "Actual", "Remaining")
            },
        )


def goals_page() -> None:
    client = get_client()
    user_id = get_user_id()
    page_header("Goals", "Savings targets")
    goals = backend_call(lambda: client.list_goals(user_id)) or []

    for goal in goals:
        current = float(goal["current_amount"]["amount"])
        target = float(goal["target_amount"]["amount"])
        st.write(f"**{goal['name']}**")
        st.progress(
            clamp_progress(current / target if target else 1.0),
            text=f"{money(current)} of {money(target)}",
        )

    add_tab, manage_tab = st.tabs(["Add goal", "Manage goals"])
    with add_tab:
        with st.form("add-goal", clear_on_submit=True):
            name = st.text_input("Goal name", max_chars=120)
            first, second = st.columns(2)
            target_amount = first.number_input("Target (SGD)", min_value=1.0, step=100.0)
            current_amount = second.number_input("Saved (SGD)", min_value=0.0, step=100.0)
            target_months = st.number_input(
                "Time horizon (months)", min_value=1, max_value=600, value=12
            )
            add_submitted = st.form_submit_button(
                "Add goal", type="primary", icon=":material/add:"
            )
        if add_submitted:
            payload = {
                "name": name.strip(),
                "target_amount": {"currency": "SGD", "amount": target_amount},
                "current_amount": {"currency": "SGD", "amount": current_amount},
                "target_months": target_months,
            }
            result = backend_call(lambda: client.create_goal(user_id, payload))
            if result:
                st.success("Goal added.")
                st.rerun()

    with manage_tab:
        if not goals:
            st.caption("No goals to manage.")
            return
        goal_id = st.selectbox(
            "Goal", [goal["id"] for goal in goals],
            format_func=lambda value: next(goal["name"] for goal in goals if goal["id"] == value),
        )
        selected = next(goal for goal in goals if goal["id"] == goal_id)
        with st.form("manage-goal"):
            edit_name = st.text_input("Goal name", value=selected["name"])
            first, second = st.columns(2)
            edit_target = first.number_input(
                "Target (SGD)", min_value=1.0, value=float(selected["target_amount"]["amount"])
            )
            edit_current = second.number_input(
                "Saved (SGD)", min_value=0.0, value=float(selected["current_amount"]["amount"])
            )
            edit_months = st.number_input(
                "Time horizon (months)",
                min_value=1,
                max_value=600,
                value=int(selected["target_months"]),
            )
            save, delete = st.columns(2)
            save_submitted = save.form_submit_button(
                "Save changes", type="primary", icon=":material/save:"
            )
            delete_submitted = delete.form_submit_button("Delete", icon=":material/delete:")
        payload = {
            "name": edit_name.strip(),
            "target_amount": {"currency": "SGD", "amount": edit_target},
            "current_amount": {"currency": "SGD", "amount": edit_current},
            "target_months": edit_months,
        }
        if save_submitted:
            result = backend_call(lambda: client.update_goal(user_id, goal_id, payload))
            if result:
                st.success("Goal updated.")
                st.rerun()
        if delete_submitted:
            backend_call(lambda: client.delete_goal(user_id, goal_id))
            st.success("Goal deleted.")
            st.rerun()


def coach_page() -> None:
    client = get_client()
    user_id = get_user_id()
    page_header("Coach", "Financial education")
    history = st.session_state.setdefault("coach_history", [])
    for message in history:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    with st.form("coach-request"):
        question = st.text_area("Question", max_chars=5000, height=110)
        submitted = st.form_submit_button(
            "Get guidance", type="primary", icon=":material/arrow_forward:"
        )
    if submitted:
        if not question.strip():
            st.warning("Enter a financial wellness question.")
            return
        response = backend_call(lambda: client.ask_coach(build_request(user_id, question)))
        if response:
            history.extend(
                [
                    {"role": "user", "content": question.strip()},
                    {"role": "assistant", "content": response["answer"]},
                ]
            )
            st.rerun()


def profile_page() -> None:
    client = get_client()
    user_id = get_user_id()
    page_header("Profile", "Financial baseline")
    profile = backend_call(lambda: client.get_profile(user_id)) or {}
    income = profile.get("monthly_income") or {"amount": 0.0}
    preferences = profile.get("preferences", {})
    risk_options = ["conservative", "moderate", "growth"]
    current_risk = profile.get("risk_tolerance") or "moderate"

    with st.form("profile"):
        display_name = st.text_input(
            "Display name", value=preferences.get("display_name", "Demo user"), max_chars=80
        )
        monthly_income = st.number_input(
            "Monthly income (SGD)", min_value=0.0, value=float(income["amount"]), step=100.0
        )
        risk_tolerance = st.segmented_control(
            "Risk comfort",
            risk_options,
            default=current_risk,
            format_func=str.title,
            selection_mode="single",
        )
        saved = st.form_submit_button("Save profile", type="primary", icon=":material/save:")
    if saved:
        payload = {
            "monthly_income": {"currency": "SGD", "amount": monthly_income},
            "risk_tolerance": risk_tolerance or "moderate",
            "preferences": {"display_name": display_name.strip() or "Demo user"},
        }
        result = backend_call(lambda: client.save_profile(user_id, payload))
        if result:
            st.success("Profile saved.")
            st.rerun()
