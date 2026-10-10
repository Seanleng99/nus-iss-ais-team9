"""Shared language control; retain explicit choices across pages and reloads."""

import streamlit as st
from coach_i18n import normalize_locale, translate

from ui.telemetry import log_event

QUERY_KEY = "coach_language"


def selection_key(user_id: str) -> str:
    # A workspace setting, independent of the active financial profile.
    log_event("VV entering ", "ui.coach_language", "selection_key")
    return "workspace-language"


def current_selection(user_id: str = "") -> str:
    log_event("VV entering ", "ui.coach_language", "current_selection")
    key = selection_key(user_id)
    if key not in st.session_state:
        # A URL can select an allowlisted output locale, never supply profile data.
        st.session_state[key] = normalize_locale(st.query_params.get(QUERY_KEY)) or "en"
        st.session_state["workspace-language-explicit"] = bool(
            normalize_locale(st.query_params.get(QUERY_KEY))
        )
    return normalize_locale(st.session_state[key]) or "en"


def save_selection(user_id: str, widget_key: str) -> None:
    log_event("VV entering ", "ui.coach_language", "save_selection")
    value = normalize_locale(st.session_state.get(widget_key))
    st.session_state[selection_key(user_id)] = value or "en"
    st.session_state["workspace-language-explicit"] = True
    _sync_url(value or "en")


def explicit_selection(user_id: str = "") -> str | None:
    log_event("VV entering ", "ui.coach_language", "explicit_selection")
    value = current_selection(user_id)
    return value if st.session_state.get("workspace-language-explicit") else None


def sync_response_locale(user_id: str, locale: str) -> None:
    log_event("VV entering ", "ui.coach_language", "sync_response_locale")
    value = normalize_locale(locale)
    if value:
        st.session_state[selection_key(user_id)] = value
        st.session_state["workspace-language-explicit"] = True
        _sync_url(value)


def apply_profile_default(user_id: str, locale: str) -> bool:
    """Align controls with a profile default until the user makes a choice."""
    log_event("VV entering ", "ui.coach_language", "apply_profile_default")
    value = normalize_locale(locale)
    if value and explicit_selection(user_id) is None and current_selection(user_id) != value:
        st.session_state[selection_key(user_id)] = value
        return True
    return False


def _sync_url(value: str | None) -> None:
    log_event("VV entering ", "ui.coach_language", "_sync_url")
    if value:
        st.query_params[QUERY_KEY] = value
    elif QUERY_KEY in st.query_params:
        del st.query_params[QUERY_KEY]


def language_selector(user_id: str, ui_locale: str, *, compact: bool = False) -> str:
    # Changing the display language changes the formatted options. Give that
    # presentation its own widget identity, backed by the canonical selection.
    log_event("VV entering ", "ui.coach_language", "language_selector")
    widget_key = f"{selection_key(user_id)}-widget-{ui_locale}"
    st.session_state[widget_key] = current_selection(user_id)
    selected = st.selectbox(
        translate("ui.language", ui_locale), ["en", "zh-Hans"],
        format_func=lambda value: translate(
            {"en": "coach.english", "zh-Hans": "coach.chinese"}[value],
            ui_locale,
        ),
        key=widget_key, on_change=save_selection, args=(user_id, widget_key),
        persist_state="session",
        label_visibility="collapsed" if compact else "visible",
    )
    value = normalize_locale(selected) or "en"
    # Navigation can clear URL parameters; restore the explicit choice from
    # the canonical session state so a reload on any page retains it.
    _sync_url(value)
    return value


def render_language_header(user_id: str) -> None:
    log_event("VV entering ", "ui.coach_language", "render_language_header")
    locale = current_selection(user_id)
    with st.container(key="workspace-language-header"), st.popover(
        translate("ui.language", locale), icon=":material/language:",
        help=translate("ui.language", locale), type="tertiary",
    ):
        language_selector(user_id, locale)
