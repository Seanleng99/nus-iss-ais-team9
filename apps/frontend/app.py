import streamlit as st

from ui.auth import logout, require_authenticated_user, signed_in_label
from ui.coach_language import render_language_header
from ui.components import apply_styles, backend_call
from ui.i18n import ui_text
from ui.pages import (
    budget_page,
    coach_page,
    create_profile_page,
    dashboard_page,
    goals_page,
    profile_page,
    transactions_page,
)
from ui.period_picker import render_period_picker
from ui.state import get_client
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
render_language_header("workspace")
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
    title=ui_text('Overview'),
    icon=":material/dashboard:",
    url_path="overview",
    default=has_active_profile,
)
transactions = st.Page(
    transactions_page,
    title=ui_text('Transactions'),
    icon=":material/receipt_long:",
    url_path="transactions",
)
budget = st.Page(
    budget_page,
    title=ui_text('Budget'),
    icon=":material/pie_chart:",
    url_path="budget",
)
goals = st.Page(
    goals_page,
    title=ui_text('Goals'),
    icon=":material/flag:",
    url_path="goals",
)
coach = st.Page(
    coach_page,
    title=ui_text('Coach'),
    icon=":material/forum:",
    url_path="coach",
)
traces = st.Page(trace_page, title=ui_text('Decision traces'), icon=":material/account_tree:", url_path="decision-traces")
profile_settings = st.Page(
    profile_page,
    title=ui_text('Profile settings'),
    icon=":material/manage_accounts:",
    url_path="profile",
)
create_profile = st.Page(
    create_profile_page,
    title=ui_text('Create profile'),
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
    st.markdown('<div class="workspace-kicker">' + ui_text("FINANCIAL WELLNESS") + '</div>', unsafe_allow_html=True)
    st.markdown('<div class="workspace-brand">' + ui_text("Coach workspace") + '</div>', unsafe_allow_html=True)
    st.caption(ui_text('Synthetic demo'))
    st.caption(ui_text('Currency: SGD (fixed)'))
    if identity_label := signed_in_label():
        st.caption(ui_text('Signed in as {v0}', v0=identity_label))
        st.button(ui_text('Sign out'), use_container_width=True, on_click=logout)

    st.markdown('<div class="sidebar-section">' + ui_text("ACCOUNT") + '</div>', unsafe_allow_html=True)
    if has_active_profile:
        profile_by_id = {profile["user_id"]: profile for profile in profiles}
        selected_user_id = st.selectbox(
            ui_text('Active profile'),
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
        st.caption(ui_text('No profiles created'))

    st.page_link(
        profile_settings,
        label=ui_text('Profile settings'),
        icon=":material/manage_accounts:",
        disabled=not has_active_profile,
        use_container_width=True,
    )
    st.page_link(
        create_profile,
        label=ui_text('Create profile'),
        icon=":material/person_add:",
        use_container_width=True,
    )

    st.markdown('<div class="sidebar-section">' + ui_text("WORKSPACE") + '</div>', unsafe_allow_html=True)
    st.page_link(
        overview,
        label=ui_text('Overview'),
        icon=":material/dashboard:",
        disabled=not has_active_profile,
    )
    st.page_link(
        transactions,
        label=ui_text('Transactions'),
        icon=":material/receipt_long:",
        disabled=not has_active_profile,
    )
    st.page_link(
        budget,
        label=ui_text('Budget'),
        icon=":material/pie_chart:",
        disabled=not has_active_profile,
    )
    st.page_link(
        goals,
        label=ui_text('Goals'),
        icon=":material/flag:",
        disabled=not has_active_profile,
    )

    render_period_picker(disabled=not has_active_profile)

    st.markdown('<div class="sidebar-section">' + ui_text("GUIDANCE") + '</div>', unsafe_allow_html=True)
    st.page_link(
        coach,
        label=ui_text('Coach'),
        icon=":material/forum:",
        disabled=not has_active_profile,
    )

    st.page_link(traces, label=ui_text('Decision traces'), icon=":material/account_tree:", disabled=not has_active_profile)

# Handle navigation from query params
if st.query_params.get("page") == "coach":
    st.query_params["page"] = ""
    st.switch_page(coach)
elif st.query_params.get("page") == "traces" and has_active_profile:
    st.query_params["page"] = ""
    st.switch_page(traces)
else:
    navigation.run()
