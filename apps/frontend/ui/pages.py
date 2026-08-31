import re
from datetime import date

import httpx
import pandas as pd
import streamlit as st

from client import build_request
from ui.components import backend_call, clamp_progress, money, page_header, percent
from ui.state import get_client, get_period_start, get_user_id

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
RISK_OPTIONS = ["conservative", "moderate", "growth"]
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EMPLOYMENT_OPTIONS = [
    "employed",
    "self-employed",
    "student",
    "unemployed",
    "retired",
    "prefer not to say",
]
OCCUPATION_OPTIONS = [
    "business and administration",
    "education",
    "engineering and technology",
    "healthcare",
    "hospitality and services",
    "public service",
    "sales and marketing",
    "skilled trades",
    "student",
    "other",
    "prefer not to say",
]
INCOME_FREQUENCY_OPTIONS = ["monthly", "fortnightly", "weekly", "irregular"]
INCOME_STABILITY_OPTIONS = ["stable", "variable", "seasonal", "not applicable"]
HOUSING_OPTIONS = [
    "family home",
    "renting",
    "homeowner with mortgage",
    "homeowner without mortgage",
    "other",
    "prefer not to say",
]
LITERACY_OPTIONS = ["beginner", "intermediate", "advanced"]
LANGUAGE_OPTIONS = ["English", "Mandarin", "Malay", "Tamil", "Other"]
ACCESSIBILITY_OPTIONS = [
    "plain language",
    "shorter responses",
    "step-by-step explanations",
    "screen-reader friendly",
]
AGE_BANDS = ["18-20", "21-25", "26-30", "31-35", "Prefer not to say"]
GENDER_OPTIONS = ["Woman", "Man", "Non-binary", "Another identity", "Prefer not to say"]
RACE_ETHNICITY_OPTIONS = [
    "Chinese",
    "Malay",
    "Indian",
    "Eurasian",
    "Other",
    "Prefer not to say",
]
RESIDENCY_OPTIONS = [
    "Singapore citizen",
    "Permanent resident",
    "Work or student pass holder",
    "Other",
    "Prefer not to say",
]
DISABILITY_OPTIONS = [
    "No disability disclosed",
    "Disability disclosed",
    "Prefer not to say",
]
MARITAL_OPTIONS = [
    "Single",
    "Married or partnered",
    "Separated or divorced",
    "Widowed",
    "Prefer not to say",
]
REGION_OPTIONS = [
    "Central",
    "East",
    "North",
    "North-East",
    "West",
    "Outside Singapore",
    "Prefer not to say",
]
COACH_STARTERS = [
    ("Review my monthly spending", ":material/receipt_long:"),
    ("Help me build an emergency fund", ":material/savings:"),
    ("Explain where my budget is tight", ":material/pie_chart:"),
    ("How can I reach my goal sooner?", ":material/flag:"),
]
AGENT_LABELS = {
    "spending": "Spending analysis",
    "budget": "Budget planning",
    "goal_strategy": "Goal planning",
    "investment_education": "Investment education",
    "risk_compliance": "Safety review",
}
RATIONALE_LABELS = {
    "MISSING_REQUIRED_INPUT": "The requested guidance needs more information.",
}


def _option_index(options: list[str], value: str | None) -> int | None:
    return options.index(value) if value in options else None


def _category_label(category: str) -> str:
    return category.replace("_", " ").title()


def _confidence_band(value: float) -> str:
    if value < 0.5:
        return "Low"
    if value < 0.8:
        return "Moderate"
    return "High"


def _render_coach_explanation(explanation: dict | None) -> None:
    if not explanation:
        return
    with st.expander("Why this answer and how certain it is"):
        st.caption(
            "Confidence is each AI component's self-assessment. It is not a "
            "probability, an accuracy guarantee, or a substitute for checking "
            "your inputs and the cited sources."
        )
        selected_agents = explanation.get("selected_agents", [])
        if selected_agents:
            labels = [
                AGENT_LABELS.get(agent, agent.replace("_", " ").title())
                for agent in selected_agents
            ]
            st.markdown(f"**Areas used:** {', '.join(labels)}")
        routing_rationale = explanation.get("routing_rationale", [])
        if routing_rationale:
            st.markdown("**Why these areas were used**")
            for rationale in routing_rationale:
                st.markdown(f"- {rationale}")
        for result in explanation.get("agent_results", []):
            agent = result.get("agent", "unknown")
            label = AGENT_LABELS.get(agent, agent.replace("_", " ").title())
            confidence = min(max(float(result.get("confidence", 0.0)), 0.0), 1.0)
            st.markdown(
                f"**{label} — {_confidence_band(confidence)} confidence "
                f"(self-assessed score {confidence:.2f})**"
            )
            for rationale in result.get("rationale", []):
                st.markdown(f"- {RATIONALE_LABELS.get(rationale, rationale)}")
        if explanation.get("blocked"):
            st.warning("The safety review blocked the requested guidance.")
        trace_id = explanation.get("trace_id")
        prompt_version = explanation.get("prompt_set_version")
        reference = f"Reference ID: {trace_id}" if trace_id else ""
        if prompt_version:
            reference = f"{reference} · Prompt set: {prompt_version}".strip(" ·")
        if reference:
            st.caption(reference)


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
            description = st.text_input(
                "Description",
                max_chars=255,
                key=f"add-transaction-{user_id}-description-v2",
            )
            first, second = st.columns(2)
            category = first.selectbox(
                "Category",
                CATEGORIES,
                index=None,
                format_func=_category_label,
                key=f"add-transaction-{user_id}-category-v2",
            )
            amount = second.number_input(
                "Amount (SGD)",
                min_value=0.0,
                value=0.0,
                step=10.0,
                key=f"add-transaction-{user_id}-amount-v2",
            )
            third, fourth = st.columns(2)
            occurred_on = third.date_input(
                "Date", value=None, key=f"add-transaction-{user_id}-date-v2"
            )
            recurring = fourth.toggle(
                "Recurring expense", key=f"add-transaction-{user_id}-recurring-v2"
            )
            add_submitted = st.form_submit_button(
                "Add transaction", type="primary", icon=":material/add:"
            )
        if add_submitted:
            if not description.strip():
                st.warning("Enter a transaction description.")
            elif category is None:
                st.warning("Select a transaction category.")
            elif amount <= 0:
                st.warning("Enter a transaction amount greater than zero.")
            elif occurred_on is None:
                st.warning("Select a transaction date.")
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
            index=None,
            format_func=lambda value: next(
                f"{item['occurred_on']} · {item['description']}"
                for item in transactions
                if item["id"] == value
            ),
            key=f"manage-transaction-{user_id}-selection-v2",
        )
        if selected_id is not None:
            selected = next(item for item in transactions if item["id"] == selected_id)
            selected_category = (
                selected["category"] if selected["category"] in CATEGORIES else "other"
            )
            with st.form("manage-transaction"):
                edit_description = st.text_input(
                    "Description",
                    value=selected["description"],
                    key=f"manage-transaction-{selected_id}-description",
                )
                first, second = st.columns(2)
                edit_category = first.selectbox(
                    "Category",
                    CATEGORIES,
                    index=CATEGORIES.index(selected_category),
                    format_func=_category_label,
                    key=f"manage-transaction-{selected_id}-category",
                )
                edit_amount = second.number_input(
                    "Amount (SGD)",
                    min_value=0.01,
                    value=float(selected["amount"]["amount"]),
                    key=f"manage-transaction-{selected_id}-amount",
                )
                third, fourth = st.columns(2)
                edit_date = third.date_input(
                    "Date",
                    value=date.fromisoformat(selected["occurred_on"]),
                    key=f"manage-transaction-{selected_id}-date",
                )
                edit_recurring = fourth.toggle(
                    "Recurring expense",
                    value=selected["recurring"],
                    key=f"manage-transaction-{selected_id}-recurring",
                )
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
                key=f"budget-{user_id}-{period_start.isoformat()}-{category}-v2",
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
            name = st.text_input(
                "Goal name", max_chars=120, key=f"add-goal-{user_id}-name-v2"
            )
            first, second = st.columns(2)
            target_amount = first.number_input(
                "Target (SGD)",
                min_value=0.0,
                value=0.0,
                step=100.0,
                key=f"add-goal-{user_id}-target-v2",
            )
            current_amount = second.number_input(
                "Saved (SGD)",
                min_value=0.0,
                value=0.0,
                step=100.0,
                key=f"add-goal-{user_id}-current-v2",
            )
            target_months = st.number_input(
                "Time horizon (months)",
                min_value=0,
                max_value=600,
                value=0,
                key=f"add-goal-{user_id}-months-v2",
            )
            add_submitted = st.form_submit_button(
                "Add goal", type="primary", icon=":material/add:"
            )
        if add_submitted:
            if not name.strip():
                st.warning("Enter a goal name.")
            elif target_amount <= 0:
                st.warning("Enter a target amount greater than zero.")
            elif target_months <= 0:
                st.warning("Enter a time horizon greater than zero.")
            else:
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
            index=None,
            format_func=lambda value: next(goal["name"] for goal in goals if goal["id"] == value),
            key=f"manage-goal-{user_id}-selection-v2",
        )
        if goal_id is not None:
            selected = next(goal for goal in goals if goal["id"] == goal_id)
            with st.form("manage-goal"):
                edit_name = st.text_input(
                    "Goal name",
                    value=selected["name"],
                    key=f"manage-goal-{goal_id}-name",
                )
                first, second = st.columns(2)
                edit_target = first.number_input(
                    "Target (SGD)",
                    min_value=1.0,
                    value=float(selected["target_amount"]["amount"]),
                    key=f"manage-goal-{goal_id}-target",
                )
                edit_current = second.number_input(
                    "Saved (SGD)",
                    min_value=0.0,
                    value=float(selected["current_amount"]["amount"]),
                    key=f"manage-goal-{goal_id}-current",
                )
                edit_months = st.number_input(
                    "Time horizon (months)",
                    min_value=1,
                    max_value=600,
                    value=int(selected["target_months"]),
                    key=f"manage-goal-{goal_id}-months",
                )
                save, delete = st.columns(2)
                save_submitted = save.form_submit_button(
                    "Save changes", type="primary", icon=":material/save:"
                )
                delete_submitted = delete.form_submit_button(
                    "Delete", icon=":material/delete:"
                )
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
    with st.container(key="coach-page-header"):
        page_header("Coach", "Financial education", marker_class="coach-shell")

    sessions = backend_call(lambda: client.list_chat_sessions(user_id)) or []
    session_by_id = {item["id"]: item for item in sessions}
    if "coach_active_session_id" not in st.session_state:
        st.session_state.coach_active_session_id = sessions[0]["id"] if sessions else None
    active_session_id = st.session_state.get("coach_active_session_id")
    if active_session_id not in session_by_id:
        active_session_id = None
        st.session_state.coach_active_session_id = None

    with st.sidebar:
        st.markdown(
            '<div class="sidebar-section coach-conversation-section">CONVERSATIONS</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "New chat",
            icon=":material/edit_square:",
            disabled=active_session_id is None,
            key="coach-new-chat",
            use_container_width=True,
        ):
            st.session_state.coach_active_session_id = None
            st.session_state.pop("coach_pending_question", None)
            st.session_state.pop("coach_rename_open", None)
            st.session_state.pop("coach_delete_open", None)
            st.rerun()

        if not sessions:
            st.caption("No saved conversations")
        for chat_session in sessions:
            session_id = chat_session["id"]
            title = chat_session["title"]
            visible_title = title if len(title) <= 38 else f"{title[:35]}..."
            with st.container(key=f"coach-conversation-row-{session_id}"):
                title_column, rename_column, delete_column = st.columns(
                    [1, 0.16, 0.16], gap="small", vertical_alignment="center"
                )
                with title_column:
                    if st.button(
                        visible_title,
                        icon=(
                            ":material/chat_bubble:"
                            if session_id == active_session_id
                            else ":material/chat_bubble_outline:"
                        ),
                        help=title,
                        key=f"coach-session-{session_id}",
                        type="primary" if session_id == active_session_id else "tertiary",
                        use_container_width=True,
                    ):
                        st.session_state.coach_active_session_id = session_id
                        st.session_state.pop("coach_pending_question", None)
                        st.session_state.pop("coach_rename_open", None)
                        st.session_state.pop("coach_delete_open", None)
                        st.rerun()
                with rename_column:
                    if st.button(
                        "Rename",
                        icon=":material/edit:",
                        help=f"Rename {title}",
                        key=f"coach-rename-action-{session_id}",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        st.session_state.coach_rename_open = session_id
                        st.session_state.pop("coach_delete_open", None)
                with delete_column:
                    if st.button(
                        "Delete",
                        icon=":material/delete:",
                        help=f"Delete {title}",
                        key=f"coach-delete-action-{session_id}",
                        type="tertiary",
                        use_container_width=True,
                    ):
                        st.session_state.coach_delete_open = session_id
                        st.session_state.pop("coach_rename_open", None)

            if st.session_state.get("coach_rename_open") == session_id:
                with st.form(f"coach-rename-form-{session_id}"):
                    renamed_title = st.text_input(
                        "Conversation title",
                        value=title,
                        max_chars=120,
                    )
                    rename_submitted = st.form_submit_button(
                        "Save", icon=":material/check:", use_container_width=True
                    )
                    if st.form_submit_button("Cancel", use_container_width=True):
                        st.session_state.pop("coach_rename_open", None)
                        st.rerun()
                if rename_submitted and renamed_title.strip():
                    backend_call(
                        lambda session_id=session_id, renamed_title=renamed_title: client.rename_chat_session(
                            user_id, session_id, renamed_title.strip()
                        )
                    )
                    st.session_state.pop("coach_rename_open", None)
                    st.rerun()

            if st.session_state.get("coach_delete_open") == session_id:
                st.warning("Delete this conversation and all of its messages?")
                if st.button(
                    "Delete conversation",
                    icon=":material/delete:",
                    type="primary",
                    key=f"coach-confirm-delete-{session_id}",
                    use_container_width=True,
                ):
                    backend_call(
                        lambda session_id=session_id: client.delete_chat_session(
                            user_id, session_id
                        )
                    )
                    if session_id == active_session_id:
                        st.session_state.coach_active_session_id = None
                    st.session_state.pop("coach_delete_open", None)
                    st.rerun()
                if st.button(
                    "Cancel",
                    key=f"coach-cancel-delete-{session_id}",
                    use_container_width=True,
                ):
                    st.session_state.pop("coach_delete_open", None)
                    st.rerun()

    pending_question = st.session_state.pop("coach_pending_question", None)
    if pending_question and active_session_id is None:
        title = pending_question[:117] + "..." if len(pending_question) > 120 else pending_question
        created_session = backend_call(
            lambda: client.create_chat_session(user_id, title)
        )
        if created_session:
            active_session_id = created_session["id"]
            st.session_state.coach_active_session_id = active_session_id

    active_session = (
        backend_call(lambda: client.get_chat_session(user_id, active_session_id))
        if active_session_id
        else None
    )
    history = active_session.get("messages", []) if active_session else []

    for message in history:
        avatar = (
            ":material/person:"
            if message["role"] == "user"
            else ":material/account_balance_wallet:"
        )
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])
            sources = message.get("sources", [])
            if sources:
                st.caption("Sources")
                for source in sources:
                    st.markdown(
                        f"- [{source['title']}]({source['canonical_url']}) — "
                        f"{source['issuing_organization']}, {source['published_at']} · "
                        f"Source ID: `{source['source_id']}`"
                    )
            _render_coach_explanation(message.get("explanation"))

    if pending_question and active_session_id:
        with st.chat_message("user", avatar=":material/person:"):
            st.markdown(pending_question)
        with st.chat_message(
            "assistant", avatar=":material/account_balance_wallet:"
        ), st.spinner("Thinking"):
            response = backend_call(
                lambda: client.ask_coach(
                    build_request(user_id, pending_question, active_session_id)
                )
            )
        if response:
            st.rerun()

    starter_question = None
    if not history:
        st.markdown(
            '<div class="coach-empty"><h2>What can I help with?</h2>'
            '<p>Ask about your spending, budget, savings, or goals.</p></div>',
            unsafe_allow_html=True,
        )
        first, second = st.columns(2)
        for index, (starter, icon) in enumerate(COACH_STARTERS):
            column = first if index % 2 == 0 else second
            if column.button(
                starter,
                icon=icon,
                key=f"coach-starter-{index}",
                use_container_width=True,
            ):
                starter_question = starter

    question = st.chat_input(
        "Message your financial coach",
        max_chars=5000,
        key=f"coach-input-{user_id}",
    )
    st.markdown(
        '<div class="coach-disclaimer">Educational guidance, not financial advice.</div>',
        unsafe_allow_html=True,
    )
    submitted_question = question or starter_question
    if submitted_question:
        normalized_question = submitted_question.strip()
        if normalized_question:
            st.session_state.coach_pending_question = normalized_question
            st.rerun()


def profile_page() -> None:
    client = get_client()
    user_id = get_user_id()
    page_header("Profile settings", "Financial baseline")
    st.caption(f"Profile ID · {user_id}")
    saved_notice = st.session_state.pop("profile_saved_notice", None)
    if saved_notice:
        st.success(saved_notice)

    profile = backend_call(lambda: client.get_profile(user_id))
    if not profile:
        st.info("This profile has not been created yet.")
        return
    context_tab, fairness_tab, delete_tab = st.tabs(
        ["Financial context", "Fairness data", "Delete profile"]
    )

    with context_tab:
        income = profile.get("monthly_income") or {"amount": 0.0}
        preferences = profile.get("preferences", {})
        current_risk = profile.get("risk_tolerance")
        with st.form("profile"):
            display_name = st.text_input(
                "Display name", value=preferences.get("display_name", ""), max_chars=80
            )
            first, second = st.columns(2)
            monthly_income = first.number_input(
                "Monthly income (SGD)",
                min_value=0.0,
                value=float(income["amount"]),
                step=100.0,
            )
            income_frequency = second.selectbox(
                "Income frequency",
                INCOME_FREQUENCY_OPTIONS,
                index=_option_index(INCOME_FREQUENCY_OPTIONS, profile.get("income_frequency")),
                key=f"profile-{user_id}-income-frequency-v2",
            )
            third, fourth = st.columns(2)
            employment_status = third.selectbox(
                "Employment status",
                EMPLOYMENT_OPTIONS,
                index=_option_index(EMPLOYMENT_OPTIONS, profile.get("employment_status")),
                format_func=str.title,
                key=f"profile-{user_id}-employment-status-v2",
            )
            occupation_category = fourth.selectbox(
                "Occupation category",
                OCCUPATION_OPTIONS,
                index=_option_index(OCCUPATION_OPTIONS, profile.get("occupation_category")),
                format_func=str.title,
                key=f"profile-{user_id}-occupation-category-v2",
            )
            fifth, sixth = st.columns(2)
            income_stability = fifth.selectbox(
                "Income stability",
                INCOME_STABILITY_OPTIONS,
                index=_option_index(INCOME_STABILITY_OPTIONS, profile.get("income_stability")),
                format_func=str.title,
                key=f"profile-{user_id}-income-stability-v2",
            )
            housing_status = sixth.selectbox(
                "Housing status",
                HOUSING_OPTIONS,
                index=_option_index(HOUSING_OPTIONS, profile.get("housing_status")),
                format_func=str.title,
                key=f"profile-{user_id}-housing-status-v2",
            )
            seventh, eighth = st.columns(2)
            household_size = seventh.number_input(
                "Household size",
                min_value=0,
                max_value=30,
                value=profile.get("household_size") or 0,
            )
            dependants = eighth.number_input(
                "Dependants",
                min_value=0,
                max_value=20,
                value=profile.get("dependants") or 0,
            )
            ninth, tenth = st.columns(2)
            financial_literacy = ninth.selectbox(
                "Financial literacy",
                LITERACY_OPTIONS,
                index=_option_index(LITERACY_OPTIONS, profile.get("financial_literacy")),
                format_func=str.title,
                key=f"profile-{user_id}-financial-literacy-v2",
            )
            preferred_language = tenth.selectbox(
                "Preferred language",
                LANGUAGE_OPTIONS,
                index=_option_index(LANGUAGE_OPTIONS, profile.get("preferred_language")),
                key=f"profile-{user_id}-preferred-language-v2",
            )
            accessibility_preferences = st.multiselect(
                "Accessibility preferences",
                ACCESSIBILITY_OPTIONS,
                default=profile.get("accessibility_preferences", []),
                format_func=str.title,
            )
            risk_tolerance = st.segmented_control(
                "Risk comfort",
                RISK_OPTIONS,
                default=current_risk,
                format_func=str.title,
                selection_mode="single",
                key=f"profile-{user_id}-risk-comfort-v2",
            )
            saved = st.form_submit_button(
                "Save profile", type="primary", icon=":material/save:"
            )
        if saved:
            if dependants and not household_size:
                st.warning("Enter a household size when dependants are provided.")
            elif household_size and dependants > household_size:
                st.warning("Dependants cannot exceed household size.")
            else:
                normalized_name = display_name.strip()
                payload = {
                    "monthly_income": {"currency": "SGD", "amount": monthly_income},
                    "risk_tolerance": risk_tolerance,
                    "employment_status": employment_status,
                    "occupation_category": occupation_category,
                    "income_frequency": income_frequency,
                    "income_stability": income_stability,
                    "household_size": household_size or None,
                    "dependants": dependants,
                    "housing_status": housing_status,
                    "financial_literacy": financial_literacy,
                    "preferred_language": preferred_language,
                    "accessibility_preferences": accessibility_preferences,
                    "preferences": (
                        {"display_name": normalized_name} if normalized_name else {}
                    ),
                }
                result = backend_call(lambda: client.save_profile(user_id, payload))
                if result:
                    st.session_state.profile_saved_notice = "Profile saved."
                    st.session_state.profile_switcher_version = (
                        st.session_state.get("profile_switcher_version", 0) + 1
                    )
                    st.rerun()

    with fairness_tab:
        fairness = backend_call(lambda: client.get_fairness_profile(user_id))
        if fairness:
            consent = fairness["consent"]
            demographics = fairness.get("demographics") or {}
            st.info(
                "Optional demographic data is stored separately for fairness evaluation. "
                "It is never included in normal coaching requests."
            )
            with st.form("fairness-consent"):
                granted = st.toggle(
                    "Allow my demographic data to be stored for fairness testing",
                    value=consent["granted"],
                )
                consent_saved = st.form_submit_button(
                    "Update consent", icon=":material/privacy_tip:"
                )
            if consent_saved:
                result = backend_call(
                    lambda: client.save_fairness_consent(user_id, granted)
                )
                if result:
                    message = (
                        "Fairness-testing consent granted."
                        if granted
                        else "Consent withdrawn and demographic data deleted."
                    )
                    st.session_state.profile_saved_notice = message
                    st.rerun()

            if consent["granted"]:
                with st.form("demographics"):
                    age_band = st.selectbox(
                        "Age band",
                        AGE_BANDS,
                        index=_option_index(AGE_BANDS, demographics.get("age_band")),
                        key=f"fairness-{user_id}-age-band-v2",
                    )
                    gender_identity = st.selectbox(
                        "Gender identity",
                        GENDER_OPTIONS,
                        index=_option_index(GENDER_OPTIONS, demographics.get("gender_identity")),
                        key=f"fairness-{user_id}-gender-identity-v2",
                    )
                    race_ethnicity = st.multiselect(
                        "Race or ethnicity",
                        RACE_ETHNICITY_OPTIONS,
                        default=demographics.get("race_ethnicity", []),
                    )
                    nationality_residency = st.selectbox(
                        "Nationality or residency",
                        RESIDENCY_OPTIONS,
                        index=_option_index(
                            RESIDENCY_OPTIONS,
                            demographics.get("nationality_residency"),
                        ),
                        key=f"fairness-{user_id}-nationality-residency-v2",
                    )
                    disability_status = st.selectbox(
                        "Disability status",
                        DISABILITY_OPTIONS,
                        index=_option_index(
                            DISABILITY_OPTIONS, demographics.get("disability_status")
                        ),
                        key=f"fairness-{user_id}-disability-status-v2",
                    )
                    marital_status = st.selectbox(
                        "Marital or family status",
                        MARITAL_OPTIONS,
                        index=_option_index(MARITAL_OPTIONS, demographics.get("marital_status")),
                        key=f"fairness-{user_id}-marital-status-v2",
                    )
                    residential_region = st.selectbox(
                        "Broad residential region",
                        REGION_OPTIONS,
                        index=_option_index(REGION_OPTIONS, demographics.get("residential_region")),
                        key=f"fairness-{user_id}-residential-region-v2",
                    )
                    demographics_saved = st.form_submit_button(
                        "Save fairness data", type="primary", icon=":material/save:"
                    )
                if demographics_saved:
                    payload = {
                        "age_band": age_band,
                        "gender_identity": gender_identity,
                        "race_ethnicity": race_ethnicity,
                        "nationality_residency": nationality_residency,
                        "disability_status": disability_status,
                        "marital_status": marital_status,
                        "residential_region": residential_region,
                    }
                    if backend_call(lambda: client.save_demographics(user_id, payload)):
                        st.success("Fairness data saved.")

    with delete_tab:
        st.warning(
            "This permanently deletes the profile and all associated financial and fairness "
            "data. This action cannot be undone."
        )
        confirmed = st.checkbox(
            "I understand that all data for this profile will be deleted",
            key=f"delete-profile-confirmed-{user_id}",
        )
        delete_requested = st.button(
            "Delete profile",
            icon=":material/delete_forever:",
            disabled=not confirmed,
            key=f"delete-profile-{user_id}",
        )
        if delete_requested and backend_call(lambda: client.delete_profile(user_id)):
            st.session_state.pop("active_user_id", None)
            st.session_state.pop("coach_active_session_id", None)
            st.session_state.pop("coach_history", None)
            st.session_state.pop("coach_pending_question", None)
            st.session_state.pop("coach_rename_open", None)
            st.session_state.pop("coach_delete_open", None)
            st.session_state.profile_switcher_version = (
                st.session_state.get("profile_switcher_version", 0) + 1
            )
            st.session_state.profile_deleted_notice = "Profile deleted."
            st.session_state.profile_deleted_redirect = True
            st.rerun()


def create_profile_page() -> None:
    client = get_client()
    page_header("Create profile", "New financial workspace")
    created_notice = st.session_state.pop("profile_created_notice", None)
    if created_notice:
        st.success(created_notice)

    with st.form("create-profile", clear_on_submit=False):
        profile_id = st.text_input(
            "Profile ID",
            max_chars=128,
            help="Letters, numbers, dots, underscores, and hyphens.",
        )
        display_name = st.text_input("Display name", max_chars=80)
        monthly_income = st.number_input(
            "Monthly income (SGD)", min_value=0.0, step=100.0
        )
        risk_tolerance = st.segmented_control(
            "Risk comfort",
            RISK_OPTIONS,
            default=None,
            format_func=str.title,
            selection_mode="single",
            key="create-profile-risk-comfort-v2",
        )
        created = st.form_submit_button(
            "Create profile", type="primary", icon=":material/person_add:"
        )

    if not created:
        return

    normalized_id = profile_id.strip()
    normalized_name = display_name.strip()
    if not PROFILE_ID_PATTERN.fullmatch(normalized_id):
        st.warning("Enter a valid profile ID.")
        return
    if not normalized_name:
        st.warning("Enter a display name.")
        return

    payload = {
        "user_id": normalized_id,
        "monthly_income": {"currency": "SGD", "amount": monthly_income},
        "risk_tolerance": risk_tolerance,
        "preferences": {"display_name": normalized_name},
    }
    try:
        result = client.create_profile(payload)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 409:
            st.error("That profile ID is already in use.")
        else:
            st.error(f"The request could not be completed ({error.response.status_code}).")
        return
    except httpx.HTTPError:
        st.error("The application service is temporarily unavailable.")
        return

    st.session_state.active_user_id = result["user_id"]
    st.session_state.profile_switcher_version = (
        st.session_state.get("profile_switcher_version", 0) + 1
    )
    st.session_state.pop("coach_active_session_id", None)
    st.session_state.pop("coach_history", None)
    st.session_state.pop("coach_pending_question", None)
    st.session_state.pop("coach_rename_open", None)
    st.session_state.pop("coach_delete_open", None)
    st.session_state.profile_created_notice = (
        f"{normalized_name} was created and is now active."
    )
    st.rerun()
