import streamlit as st

from ui.auth import logout, require_authenticated_user, signed_in_label
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
from ui.styles import SPENDING_INSIGHTS_CSS
from ui.telemetry import configure_logging
from ui.trace_viewer import trace_page

configure_logging()
st.set_page_config(
    page_title="Financial Wellness Coach",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
    initial_sidebar_state="auto",
)
apply_styles()
st.markdown(SPENDING_INSIGHTS_CSS, unsafe_allow_html=True)
require_authenticated_user()

client = get_client()
profiles = backend_call(client.list_profiles) or []
profiles = sorted(
    profiles,
    key=lambda profile: (profile["display_name"].casefold(), profile["user_id"]),
)
profile_ids = [profile["user_id"] for profile in profiles]
active_user_id = st.session_state.get("active_user_id")
if profile_ids and active_user_id not in profile_ids:
    active_user_id = profile_ids[0]
    st.session_state.active_user_id = active_user_id
elif not profile_ids:
    active_user_id = None
    st.session_state.pop("active_user_id", None)

has_active_profile = active_user_id in profile_ids

overview = st.Page(
    dashboard_page,
    title="Overview",
    icon=":material/dashboard:",
    url_path="overview",
    default=has_active_profile,
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
traces = st.Page(trace_page, title="Decision traces", icon=":material/account_tree:", url_path="decision-traces")
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
    default=not has_active_profile,
)
navigation = st.navigation(
    (
        [
            overview,
            transactions,
            budget,
            goals,
            coach,
            traces,
            profile_settings,
            create_profile,
        ]
        if has_active_profile
        else [create_profile]
    ),
    position="hidden",
)

if st.session_state.pop("profile_deleted_redirect", False):
    st.switch_page(overview if has_active_profile else create_profile)
if deleted_notice := st.session_state.pop("profile_deleted_notice", None):
    st.toast(deleted_notice, icon=":material/delete:")

with st.sidebar:
    st.markdown('<div class="workspace-kicker">FINANCIAL WELLNESS</div>', unsafe_allow_html=True)
    st.markdown('<div class="workspace-brand">Coach workspace</div>', unsafe_allow_html=True)
    st.caption("Synthetic demo")
    if identity_label := signed_in_label():
        st.caption(f"Signed in as {identity_label}")
        if st.button("Sign out", use_container_width=True):
            logout()

    st.markdown('<div class="sidebar-section">ACCOUNT</div>', unsafe_allow_html=True)
    if has_active_profile:
        profile_by_id = {profile["user_id"]: profile for profile in profiles}
        selected_user_id = st.selectbox(
            "Active profile",
            profile_ids,
            index=profile_ids.index(active_user_id),
            format_func=lambda user_id: f"{profile_by_id[user_id]['display_name']} · {user_id}",
            key=(f"profile-switcher-{st.session_state.get('profile_switcher_version', 0)}"),
        )
        if selected_user_id != st.session_state.get("active_user_id"):
            st.session_state.active_user_id = selected_user_id
            st.session_state.pop("coach_active_session_id", None)
            st.session_state.pop("coach_history", None)
            st.session_state.pop("coach_pending_question", None)
            st.session_state.pop("coach_pending_render", None)
            st.session_state.pop("coach_rename_open", None)
            st.session_state.pop("coach_delete_open", None)
        active_user_id = selected_user_id
    else:
        st.caption("No profiles created")

    st.page_link(
        profile_settings,
        label="Profile settings",
        icon=":material/manage_accounts:",
        disabled=not has_active_profile,
        use_container_width=True,
    )
    st.page_link(
        create_profile,
        label="Create profile",
        icon=":material/person_add:",
        use_container_width=True,
    )

    st.markdown('<div class="sidebar-section">WORKSPACE</div>', unsafe_allow_html=True)
    st.page_link(
        overview,
        label="Overview",
        icon=":material/dashboard:",
        disabled=not has_active_profile,
    )
    st.page_link(
        transactions,
        label="Transactions",
        icon=":material/receipt_long:",
        disabled=not has_active_profile,
    )
    st.page_link(
        budget,
        label="Budget",
        icon=":material/pie_chart:",
        disabled=not has_active_profile,
    )
    st.page_link(
        goals,
        label="Goals",
        icon=":material/flag:",
        disabled=not has_active_profile,
    )

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
        disabled=not has_active_profile,
    )

    st.markdown('<div class="sidebar-section">GUIDANCE</div>', unsafe_allow_html=True)
    st.page_link(
        coach,
        label="Coach",
        icon=":material/forum:",
        disabled=not has_active_profile,
    )

    st.page_link(traces, label="Decision traces", icon=":material/account_tree:", disabled=not has_active_profile)

# Handle navigation from query params
if st.query_params.get("page") == "coach":
    st.query_params["page"] = ""
    st.switch_page(coach)
elif st.query_params.get("page") == "traces" and has_active_profile:
    st.query_params["page"] = ""
    st.switch_page(traces)
else:
    navigation.run()
