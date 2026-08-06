import streamlit as st

from ui.components import apply_styles, backend_call
from ui.pages import (
    budget_page,
    coach_page,
    create_profile_page,
    dashboard_page,
    goals_page,
    profile_page,
    transactions_page,
)
from ui.state import get_client, period_options, today_singapore

st.set_page_config(
    page_title="Financial Wellness Coach",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
    initial_sidebar_state="auto",
)
apply_styles()

overview = st.Page(
    dashboard_page,
    title="Overview",
    icon=":material/dashboard:",
    url_path="overview",
    default=True,
)
transactions = st.Page(
    transactions_page,
    title="Transactions",
    icon=":material/receipt_long:",
    url_path="transactions",
)
budget = st.Page(
    budget_page,
    title="Budget",
    icon=":material/pie_chart:",
    url_path="budget",
)
goals = st.Page(
    goals_page,
    title="Goals",
    icon=":material/flag:",
    url_path="goals",
)
coach = st.Page(
    coach_page,
    title="Coach",
    icon=":material/forum:",
    url_path="coach",
)
profile_settings = st.Page(
    profile_page,
    title="Profile settings",
    icon=":material/manage_accounts:",
    url_path="profile",
)
create_profile = st.Page(
    create_profile_page,
    title="Create profile",
    icon=":material/person_add:",
    url_path="create-profile",
)
navigation = st.navigation(
    [
        overview,
        transactions,
        budget,
        goals,
        coach,
        profile_settings,
        create_profile,
    ],
    position="hidden",
)

client = get_client()
profiles = backend_call(client.list_profiles) or []
profiles = sorted(
    profiles,
    key=lambda profile: (profile["display_name"].casefold(), profile["user_id"]),
)
profile_ids = [profile["user_id"] for profile in profiles]
active_user_id = st.session_state.get("active_user_id", "demo-user")
if profile_ids and active_user_id not in profile_ids:
    active_user_id = profile_ids[0]

with st.sidebar:
    st.markdown('<div class="workspace-kicker">FINANCIAL WELLNESS</div>', unsafe_allow_html=True)
    st.markdown('<div class="workspace-brand">Coach workspace</div>', unsafe_allow_html=True)
    st.caption("Synthetic demo")

    st.markdown('<div class="sidebar-section">ACCOUNT</div>', unsafe_allow_html=True)
    if profiles:
        profile_by_id = {profile["user_id"]: profile for profile in profiles}
        selected_user_id = st.selectbox(
            "Active profile",
            profile_ids,
            index=profile_ids.index(active_user_id),
            format_func=lambda user_id: (
                f"{profile_by_id[user_id]['display_name']} · {user_id}"
            ),
            key=(
                "profile-switcher-"
                f"{st.session_state.get('profile_switcher_version', 0)}"
            ),
        )
        if selected_user_id != st.session_state.get("active_user_id"):
            st.session_state.active_user_id = selected_user_id
            st.session_state.pop("coach_history", None)
        active_user_id = selected_user_id
    else:
        st.session_state.active_user_id = active_user_id
        st.caption("No profiles created")

    st.page_link(
        profile_settings,
        label="Profile settings",
        icon=":material/manage_accounts:",
        disabled=not profiles,
        use_container_width=True,
    )
    st.page_link(
        create_profile,
        label="Create profile",
        icon=":material/person_add:",
        use_container_width=True,
    )

    st.markdown('<div class="sidebar-section">WORKSPACE</div>', unsafe_allow_html=True)
    st.page_link(overview, label="Overview", icon=":material/dashboard:")
    st.page_link(transactions, label="Transactions", icon=":material/receipt_long:")
    st.page_link(budget, label="Budget", icon=":material/pie_chart:")
    st.page_link(goals, label="Goals", icon=":material/flag:")

    periods = period_options()
    current = today_singapore()
    current_period = current.replace(day=1)
    selected_period = st.session_state.get("active_period", current_period)
    selected_index = periods.index(selected_period) if selected_period in periods else 2
    st.session_state.active_period = st.selectbox(
        "Period",
        periods,
        index=selected_index,
        format_func=lambda value: value.strftime("%B %Y"),
    )

    st.markdown('<div class="sidebar-section">GUIDANCE</div>', unsafe_allow_html=True)
    st.page_link(coach, label="Coach", icon=":material/forum:")

navigation.run()
