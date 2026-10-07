from collections.abc import Callable
from typing import Any

import httpx
import streamlit as st

from ui.i18n import ui_text


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root { --ink: #17211d; --muted: #64716b; --line: #dfe7e2; --green: #18794e; }
        html, body, [class*="css"] { letter-spacing: 0 !important; }
        .stApp { background: #f7f9f7; color: var(--ink); }
        [data-testid="stHeader"] {
            background: #f7f9f7 !important; height: 2.5rem !important;
            min-height: 2.5rem !important;
        }
        [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
        [data-testid="stMainBlockContainer"] { padding-top: 1.5rem; }
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"]
        > [data-testid="stLayoutWrapper"]:has(> .st-key-workspace-language-header) {
            position: fixed; top: 0; right: 2.75rem; width: 2.5rem;
            z-index: 1000001;
        }
        .st-key-workspace-language-header [data-testid="stPopoverButton"] {
            width: 2.5rem; height: 2.5rem; min-height: 2.5rem; padding: 0;
        }
        .st-key-workspace-language-header [data-testid="stPopoverButton"]
        [data-testid="stMarkdownContainer"] {
            position: absolute; width: 1px; height: 1px; overflow: hidden;
            clip-path: inset(50%); white-space: nowrap;
        }
        .st-key-workspace-language-header [data-testid="stPopoverButton"] [aria-hidden="true"] { display: none; }
        /* The deployed workspace exposes viewer controls, not Streamlit deployment. */
        [data-testid="stAppDeployButton"] { display: none; }
        /* Page-level spinners still show progress without covering Language. */
        [data-testid="stStatusWidget"] { display: none; }
        [data-testid="stSidebarContent"] { gap: 0; }
        [data-testid="stSidebarHeader"] {
            height: 2.5rem; position: absolute; right: 0.5rem; top: 0.5rem; z-index: 1;
        }
        [data-testid="stSidebarUserContent"] { padding-top: 2.5rem; }
        [data-testid="stSidebar"] h1 { color: var(--ink); font-size: 1.3rem; }
        [data-testid="stMetric"] {
            background: #ffffff; border: 1px solid var(--line); border-radius: 6px;
            padding: 0.8rem 1rem;
        }
        [data-testid="stMetricValue"] { color: var(--ink); font-size: 1.55rem; }
        div[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 6px; }
        .workspace-brand { font-weight: 750; font-size: 1.05rem; color: var(--ink); }
        .workspace-kicker { color: var(--green); font-weight: 650; font-size: 0.75rem; }
        .sidebar-section {
            border-top: 1px solid var(--line); color: var(--muted); font-size: 0.72rem;
            font-weight: 700; margin-top: 1rem; padding-top: 0.9rem;
        }
        .page-heading {
            color: var(--ink); font-size: 1.8rem; line-height: 1.2;
            margin: 0 !important; padding: 0 !important;
        }
        .page-subheading { color: var(--muted); margin: 0.3rem 0 1.2rem 0; }
        .section-rule { border-top: 1px solid var(--line); margin: 1rem 0; }
        .stButton > button, .stFormSubmitButton > button { border-radius: 6px; }
        .stApp:has(.coach-shell) [data-testid="stMainBlockContainer"] {
            padding-bottom: 7rem;
        }
        .stApp:has(.coach-shell) [data-testid="stLayoutWrapper"]:has(
            > .st-key-coach-page-header
        ) {
            background: #f7f9f7; position: sticky; top: 2.5rem; z-index: 3;
        }
        .stApp:has(.coach-shell) .st-key-coach-page-header { position: static; }
        .stApp:has(.coach-shell) .st-key-coach-page-header .page-subheading {
            margin-bottom: 0.65rem;
        }
        .stApp:has(.coach-shell) .coach-conversation-section { margin-top: 1rem; }
        .st-key-coach-conversation-list { gap: 0.15rem !important; }
        .st-key-workspace-period-picker > [data-testid="stVerticalBlock"] { gap: 0.3rem; }
        .st-key-workspace-period-picker [data-testid="stHorizontalBlock"],
        .st-key-workspace-period-months [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap !important;
        }
        .st-key-workspace-period-picker [data-testid="stColumn"],
        .st-key-workspace-period-months [data-testid="stColumn"] {
            min-width: 0 !important;
        }
        .st-key-workspace-period-picker button { padding-left: 0.3rem; padding-right: 0.3rem; }
        .st-key-workspace-period-months { gap: 0.5rem !important; }
        .st-key-workspace-period-months button {
            padding: 0.25rem 0.35rem; min-height: 2.125rem; white-space: nowrap;
        }
        .st-key-workspace-period-months button p { font-size: 0.875rem; white-space: nowrap; }
        .stApp:has(.coach-shell) .st-key-coach-new-chat button,
        .stApp:has(.coach-shell) [class*="st-key-coach-session-"] button {
            gap: 0.5rem; justify-content: flex-start; min-height: 2.125rem;
            overflow: hidden; padding-left: 0.65rem; padding-right: 0.65rem; text-align: left;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-conversation-row-"] {
            margin: 0; padding: 0; position: relative;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-conversation-row-"]
        > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-coach-conversation-actions-"]) {
            position: absolute; top: 0.125rem; right: 0.125rem;
            width: 4rem; z-index: 1;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-conversation-actions-"] {
            background: #ffffff; border-radius: 6px; gap: 0.125rem !important;
        }
        @media (hover: hover) and (pointer: fine) {
            .stApp:has(.coach-shell) [class*="st-key-coach-conversation-row-"]
            > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-coach-conversation-actions-"]) {
                opacity: 0; pointer-events: none;
            }
            .stApp:has(.coach-shell) [class*="st-key-coach-conversation-row-"]:is(:hover, :has(:focus-visible))
            > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-coach-conversation-actions-"]) {
                opacity: 1; pointer-events: auto;
            }
        }
        .stApp:has(.coach-shell) .st-key-coach-conversation-list [data-testid="stForm"] {
            border: 0; padding: 0;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-conversation-row-"]
        [data-testid="stHorizontalBlock"] { gap: 0; }
        .stApp:has(.coach-shell) [class*="st-key-coach-session-"] button p {
            flex: 1 1 0 !important; min-width: 0; overflow: hidden; text-align: left;
            max-width: none; text-overflow: clip; white-space: nowrap;
            line-height: 1.35; width: auto !important;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-session-"]
        button > div > span {
            justify-content: flex-start; align-items: flex-start; overflow: visible; width: 100%;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-session-"]
        [data-testid="stIconMaterial"] {
            flex: 0 0 1rem;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-rename-action-"] button,
        .stApp:has(.coach-shell) [class*="st-key-coach-delete-action-"] button,
        .stApp:has(.coach-shell) .st-key-coach-conversation-list [data-testid="stFormSubmitButton"] button {
            height: 1.875rem; justify-content: center; min-height: 1.875rem;
            min-width: 1.875rem; padding: 0.2rem; width: 1.875rem !important;
        }
        .stApp:has(.coach-shell) [class*="st-key-coach-rename-action-"] button p,
        .stApp:has(.coach-shell) [class*="st-key-coach-delete-action-"] button p,
        .stApp:has(.coach-shell) .st-key-coach-conversation-list [data-testid="stFormSubmitButton"] button p {
            position: absolute; width: 1px; height: 1px; overflow: hidden;
            clip-path: inset(50%); white-space: nowrap;
        }
        .stApp:has(.coach-shell) [data-testid="stChatMessage"] {
            background: transparent; border: 0; padding: 0.75rem 0;
        }
        .stApp:has(.coach-shell) [data-testid="stChatMessage"]:has(
            [aria-label="Chat message from user"]
        ) { justify-content: flex-end; }
        .stApp:has(.coach-shell) [data-testid="stChatMessage"]:has(
            [aria-label="Chat message from user"]
        ) [data-testid="stChatMessageAvatarCustom"] { display: none; }
        .stApp:has(.coach-shell) [aria-label="Chat message from user"] {
            background: #e9efeb; border-radius: 8px; flex: 0 1 auto;
            margin: 0; max-width: 78%; padding: 0.65rem 0.9rem;
        }
        .stApp:has(.coach-shell) [data-testid="stChatInput"] {
            background: #ffffff; border: 1px solid #cbd8d0; border-radius: 8px;
            box-shadow: 0 2px 10px rgba(23, 33, 29, 0.08);
        }
        .stApp:has(.coach-shell) [data-testid="stBottomBlockContainer"] {
            background: #f7f9f7; padding-top: 0.75rem;
        }
        .coach-empty { margin: 12vh auto 1.5rem auto; text-align: center; }
        .coach-empty h2 { color: var(--ink); font-size: 1.65rem; margin: 0; }
        .coach-empty p { color: var(--muted); margin: 0.5rem 0 0 0; }
        .coach-disclaimer { color: var(--muted); font-size: 0.78rem; text-align: center; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str, marker_class: str | None = None) -> None:
    heading_class = f"page-heading {marker_class}" if marker_class else "page-heading"
    st.markdown(f'<h1 class="{heading_class}">{title}</h1>', unsafe_allow_html=True)
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
        st.error(ui_text('The request could not be completed ({v0}).', v0=error.response.status_code))
    except httpx.HTTPError:
        st.error(ui_text('The application service is temporarily unavailable.'))
    return None
