from collections.abc import Callable
from typing import Any

import httpx
import streamlit as st


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --ink: #17211d; --muted: #64716b; --line: #dfe7e2; --green: #18794e; }
        html, body, [class*="css"] { letter-spacing: 0 !important; }
        .stApp { background: #f7f9f7; color: var(--ink); }
        [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
        [data-testid="stSidebar"] h1 { color: var(--ink); font-size: 1.3rem; }
        [data-testid="stMetric"] {
            background: #ffffff; border: 1px solid var(--line); border-radius: 6px;
            padding: 0.8rem 1rem;
        }
        [data-testid="stMetricValue"] { color: var(--ink); font-size: 1.55rem; }
        div[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 6px; }
        .workspace-brand { font-weight: 750; font-size: 1.05rem; color: var(--ink); }
        .workspace-kicker { color: var(--green); font-weight: 650; font-size: 0.75rem; }
        .page-heading { margin: 0; color: var(--ink); font-size: 1.8rem; line-height: 1.2; }
        .page-subheading { color: var(--muted); margin: 0.3rem 0 1.2rem 0; }
        .section-rule { border-top: 1px solid var(--line); margin: 1rem 0; }
        .stButton > button, .stFormSubmitButton > button { border-radius: 6px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str) -> None:
    st.markdown(f'<h1 class="page-heading">{title}</h1>', unsafe_allow_html=True)
    st.markdown(f'<p class="page-subheading">{subtitle}</p>', unsafe_allow_html=True)


def money(amount: float, currency: str = "SGD") -> str:
    return f"{currency} {amount:,.2f}"


def percent(value: float) -> str:
    return f"{value:.1f}%"


def clamp_progress(value: float) -> float:
    return max(0.0, min(value, 1.0))


def backend_call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except httpx.HTTPStatusError as error:
        st.error(f"The request could not be completed ({error.response.status_code}).")
    except httpx.HTTPError:
        st.error("The application service is temporarily unavailable.")
    return None
