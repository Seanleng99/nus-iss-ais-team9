from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from client import BackendClient
from ui.auth import current_identity_token
from ui.telemetry import log_event

SINGAPORE_TIMEZONE = ZoneInfo("Asia/Singapore")


def today_singapore() -> date:
    log_event("VV entering ", "ui.state", "today_singapore")
    return datetime.now(SINGAPORE_TIMEZONE).date()


def shift_month(period_start: date, offset: int) -> date:
    log_event("VV entering ", "ui.state", "shift_month")
    month_index = period_start.year * 12 + period_start.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def period_options() -> list[date]:
    log_event("VV entering ", "ui.state", "period_options")
    today = today_singapore()
    current = date(today.year, today.month, 1)
    return [shift_month(current, offset) for offset in range(2, -13, -1)]


def get_client() -> BackendClient:
    log_event("VV entering ", "ui.state", "get_client")
    identity_token = current_identity_token()
    existing_token = st.session_state.get("backend_client_identity_token")
    journey_id = st.session_state.get("journey_id")
    existing_journey = st.session_state.get("backend_client_journey_id")
    if (
        "backend_client" not in st.session_state
        or existing_token != identity_token
        or existing_journey != journey_id
    ):
        st.session_state.backend_client = BackendClient(
            id_token=identity_token, journey_id=journey_id
        )
        st.session_state.backend_client_identity_token = identity_token
        st.session_state.backend_client_journey_id = journey_id
    return st.session_state.backend_client


def get_user_id() -> str:
    log_event("VV entering ", "ui.state", "get_user_id")
    return st.session_state.get("active_user_id", "demo-user")


def get_period_start() -> date:
    log_event("VV entering ", "ui.state", "get_period_start")
    today = today_singapore()
    return st.session_state.get("active_period", date(today.year, today.month, 1))
