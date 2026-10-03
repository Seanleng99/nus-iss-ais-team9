"""Shared language control; retain explicit choices across pages and reloads."""

import streamlit as st
from coach_i18n import normalize_locale, translate

QUERY_KEY = "coach_language"


def selection_key(user_id: str) -> str:
    # A workspace setting, independent of the active financial profile.
    return "workspace-language"


def current_selection(user_id: str = "") -> str:
    key = selection_key(user_id)
    if key not in st.session_state:
        # A URL can select an allowlisted output locale, never supply profile data.
        st.session_state[key] = normalize_locale(st.query_params.get(QUERY_KEY)) or "en"
    return normalize_locale(st.session_state[key]) or "en"


def save_selection(user_id: str, widget_key: str) -> None:
    value = normalize_locale(st.session_state.get(widget_key))
    st.session_state[selection_key(user_id)] = value or "en"
    _sync_url(value or "en")


def _sync_url(value: str | None) -> None:
    if value:
        st.query_params[QUERY_KEY] = value
    elif QUERY_KEY in st.query_params:
        del st.query_params[QUERY_KEY]


def language_selector(user_id: str, ui_locale: str, *, compact: bool = False) -> str:
    # Changing the display language changes the formatted options. Give that
    # presentation its own widget identity, backed by the canonical selection.
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
    locale = current_selection(user_id)
    with st.container(key="workspace-language-header"), st.popover(
        translate("ui.language", locale), icon=":material/language:",
        help=translate("ui.language", locale), type="tertiary",
    ):
        language_selector(user_id, locale)
