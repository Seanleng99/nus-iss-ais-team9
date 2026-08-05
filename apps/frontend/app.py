import streamlit as st

from ui.components import apply_styles
from ui.pages import (
    budget_page,
    coach_page,
    dashboard_page,
    goals_page,
    profile_page,
    transactions_page,
)
from ui.state import period_options, today_singapore

st.set_page_config(
    page_title="Financial Wellness Coach",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
    initial_sidebar_state="auto",
)
apply_styles()

with st.sidebar:
    st.markdown('<div class="workspace-kicker">FINANCIAL WELLNESS</div>', unsafe_allow_html=True)
    st.markdown('<div class="workspace-brand">Coach workspace</div>', unsafe_allow_html=True)
    st.caption("Synthetic demo")
    st.session_state.active_user_id = st.text_input(
        "Profile ID", value=st.session_state.get("active_user_id", "demo-user"), max_chars=128
    ).strip() or "demo-user"
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

navigation = st.navigation(
    {
        "Workspace": [
            st.Page(dashboard_page, title="Overview", icon=":material/dashboard:", default=True),
            st.Page(
                transactions_page,
                title="Transactions",
                icon=":material/receipt_long:",
            ),
            st.Page(budget_page, title="Budget", icon=":material/pie_chart:"),
            st.Page(goals_page, title="Goals", icon=":material/flag:"),
        ],
        "Guidance": [
            st.Page(coach_page, title="Coach", icon=":material/forum:"),
        ],
        "Account": [
            st.Page(profile_page, title="Profile", icon=":material/manage_accounts:"),
        ],
    }
)
navigation.run()
