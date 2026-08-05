from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from client import BackendClient

SINGAPORE_TIMEZONE = ZoneInfo("Asia/Singapore")


def today_singapore() -> date:
    return datetime.now(SINGAPORE_TIMEZONE).date()


def shift_month(period_start: date, offset: int) -> date:
    month_index = period_start.year * 12 + period_start.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def period_options() -> list[date]:
    today = today_singapore()
    current = date(today.year, today.month, 1)
    return [shift_month(current, offset) for offset in range(2, -13, -1)]


def get_client() -> BackendClient:
    if "backend_client" not in st.session_state:
        st.session_state.backend_client = BackendClient()
    return st.session_state.backend_client


def get_user_id() -> str:
    return st.session_state.get("active_user_id", "demo-user")


def get_period_start() -> date:
    today = today_singapore()
    return st.session_state.get("active_period", date(today.year, today.month, 1))
