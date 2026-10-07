from datetime import date

from coach_i18n import translate
from streamlit.testing.v1 import AppTest


def picker(period=date(2026, 10, 1)):
    app = AppTest.from_string(
        "from ui.period_picker import render_period_picker\nrender_period_picker()"
    )
    app.session_state["active_period"] = period
    return app.run()


def test_select_month_in_another_year_preserves_period_on_rerun():
    app = picker()
    app.number_input(key="workspace-period-year").set_value(2023).run()
    # Browsing years does not change the workspace until a month is chosen.
    assert app.session_state["active_period"] == date(2026, 10, 1)
    app.button(key="workspace-period-month-2").click().run()
    assert not app.exception
    assert app.session_state["active_period"] == date(2023, 2, 1)
    app.run()
    assert app.session_state["active_period"] == date(2023, 2, 1)


def test_today_uses_singapore_and_picker_has_no_month_arrows(monkeypatch):
    from ui import period_picker

    monkeypatch.setattr(period_picker, "today_singapore", lambda: date(2026, 10, 7))
    app = picker(date(2026, 1, 1))
    assert not any(
        button.key in {"workspace-period-previous", "workspace-period-next"}
        for button in app.button
    )
    app.button(key="workspace-period-today").click().run()
    assert app.session_state["active_period"] == date(2026, 10, 1)
    assert not app.exception


def test_language_change_keeps_chosen_month_and_localizes_controls():
    app = picker(date(2024, 5, 1))
    app.session_state["workspace-language"] = "zh-Hans"
    app.run()
    assert not app.exception
    assert app.session_state["active_period"] == date(2024, 5, 1)
    assert app.number_input(key="workspace-period-year").label == translate(
        "ui.text.period_year", "zh-Hans"
    )
    assert app.button(key="workspace-period-month-5").label == translate(
        "ui.period.month_5", "zh-Hans"
    )


def test_empty_year_keeps_period_and_disables_month_choices():
    app = picker()
    app.number_input(key="workspace-period-year").set_value(None).run()
    assert not app.exception
    assert app.session_state["active_period"] == date(2026, 10, 1)
    assert app.button(key="workspace-period-month-1").disabled
    app.button(key="workspace-period-today").click().run()
    assert app.number_input(key="workspace-period-year").value == 2026
