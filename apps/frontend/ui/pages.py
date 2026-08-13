import re
from datetime import date

import httpx
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


def _option_index(options: list[str], value: str | None, default: int = 0) -> int:
    return options.index(value) if value in options else default


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
    page_header("Profile settings", "Financial baseline")
    st.caption(f"Profile ID · {user_id}")
    saved_notice = st.session_state.pop("profile_saved_notice", None)
    if saved_notice:
        st.success(saved_notice)

    profile = backend_call(lambda: client.get_profile(user_id))
    if not profile:
        st.info("This profile has not been created yet.")
        return
    context_tab, fairness_tab = st.tabs(["Financial context", "Fairness data"])

    with context_tab:
        income = profile.get("monthly_income") or {"amount": 0.0}
        preferences = profile.get("preferences", {})
        current_risk = profile.get("risk_tolerance") or "moderate"
        with st.form("profile"):
            display_name = st.text_input(
                "Display name", value=preferences.get("display_name", user_id), max_chars=80
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
            )
            third, fourth = st.columns(2)
            employment_status = third.selectbox(
                "Employment status",
                EMPLOYMENT_OPTIONS,
                index=_option_index(EMPLOYMENT_OPTIONS, profile.get("employment_status")),
                format_func=str.title,
            )
            occupation_category = fourth.selectbox(
                "Occupation category",
                OCCUPATION_OPTIONS,
                index=_option_index(OCCUPATION_OPTIONS, profile.get("occupation_category")),
                format_func=str.title,
            )
            fifth, sixth = st.columns(2)
            income_stability = fifth.selectbox(
                "Income stability",
                INCOME_STABILITY_OPTIONS,
                index=_option_index(INCOME_STABILITY_OPTIONS, profile.get("income_stability")),
                format_func=str.title,
            )
            housing_status = sixth.selectbox(
                "Housing status",
                HOUSING_OPTIONS,
                index=_option_index(HOUSING_OPTIONS, profile.get("housing_status")),
                format_func=str.title,
            )
            seventh, eighth = st.columns(2)
            household_size = seventh.number_input(
                "Household size",
                min_value=1,
                max_value=30,
                value=profile.get("household_size") or 1,
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
            )
            preferred_language = tenth.selectbox(
                "Preferred language",
                LANGUAGE_OPTIONS,
                index=_option_index(LANGUAGE_OPTIONS, profile.get("preferred_language")),
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
            )
            saved = st.form_submit_button(
                "Save profile", type="primary", icon=":material/save:"
            )
        if saved:
            if dependants > household_size:
                st.warning("Dependants cannot exceed household size.")
            else:
                payload = {
                    "monthly_income": {"currency": "SGD", "amount": monthly_income},
                    "risk_tolerance": risk_tolerance or "moderate",
                    "employment_status": employment_status,
                    "occupation_category": occupation_category,
                    "income_frequency": income_frequency,
                    "income_stability": income_stability,
                    "household_size": household_size,
                    "dependants": dependants,
                    "housing_status": housing_status,
                    "financial_literacy": financial_literacy,
                    "preferred_language": preferred_language,
                    "accessibility_preferences": accessibility_preferences,
                    "preferences": {"display_name": display_name.strip() or user_id},
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
                        index=_option_index(AGE_BANDS, demographics.get("age_band"), 4),
                    )
                    gender_identity = st.selectbox(
                        "Gender identity",
                        GENDER_OPTIONS,
                        index=_option_index(
                            GENDER_OPTIONS, demographics.get("gender_identity"), 4
                        ),
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
                            4,
                        ),
                    )
                    disability_status = st.selectbox(
                        "Disability status",
                        DISABILITY_OPTIONS,
                        index=_option_index(
                            DISABILITY_OPTIONS, demographics.get("disability_status"), 2
                        ),
                    )
                    marital_status = st.selectbox(
                        "Marital or family status",
                        MARITAL_OPTIONS,
                        index=_option_index(
                            MARITAL_OPTIONS, demographics.get("marital_status"), 4
                        ),
                    )
                    residential_region = st.selectbox(
                        "Broad residential region",
                        REGION_OPTIONS,
                        index=_option_index(
                            REGION_OPTIONS, demographics.get("residential_region"), 6
                        ),
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
            default="moderate",
            format_func=str.title,
            selection_mode="single",
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
        "risk_tolerance": risk_tolerance or "moderate",
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
    st.session_state.pop("coach_history", None)
    st.session_state.profile_created_notice = (
        f"{normalized_name} was created and is now active."
    )
    st.rerun()
