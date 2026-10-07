"""Compact month selection shared by all workspace pages."""

from datetime import date

import streamlit as st
from coach_i18n import translate

from ui.coach_language import current_selection
from ui.i18n import month_label, ui_text
from ui.state import get_period_start, today_singapore


def _select_period(period: date) -> None:
    st.session_state.active_period = period.replace(day=1)
    st.session_state["workspace-period-year"] = period.year


def render_period_picker(*, disabled: bool = False) -> None:
    selected = get_period_start().replace(day=1)
    st.session_state.active_period = selected
    if "workspace-period-year" not in st.session_state:
        st.session_state["workspace-period-year"] = selected.year
    locale = current_selection()
    with st.container(key="workspace-period-picker", gap="small"):
        st.caption(ui_text("Period"))
        with st.popover(
            month_label(selected, locale), icon=":material/calendar_month:",
            disabled=disabled, use_container_width=True,
        ):
            year = st.number_input(
                ui_text("Year"), min_value=1, max_value=9999,
                value=None, step=1, key="workspace-period-year", disabled=disabled,
            )
            with st.container(key="workspace-period-months", gap="small"):
                for first_month in range(1, 13, 3):
                    columns = st.columns(3, gap="small")
                    for month, column in zip(range(first_month, first_month + 3), columns):
                        with column:
                            st.button(
                                translate(f"ui.period.month_{month}", locale),
                                key=f"workspace-period-month-{month}",
                                type="primary" if (year, month) == (
                                    selected.year, selected.month
                                ) else "secondary",
                                use_container_width=True, disabled=disabled or year is None,
                                on_click=_select_period,
                                args=(date(year or selected.year, month, 1),),
                            )
            st.button(
                ui_text("This month"), key="workspace-period-today",
                use_container_width=True, disabled=disabled,
                on_click=_select_period, args=(today_singapore(),),
            )
