from streamlit.testing.v1 import AppTest


def test_multi_month_inputs_are_explicit_and_do_not_save():
    app = AppTest.from_string("""
from datetime import date
from ui.budget_continuity import render_continuity
class Client:
    def preview_budget_months(self, *args): raise AssertionError('Incomplete input')
    def confirm_budget_months(self, *args): raise AssertionError('No confirmation')
render_continuity(Client(), 'u', date(2026,9,1))
""").run(timeout=30)
    assert not app.exception
    next(b for b in app.button if b.label == "Preview monthly plans").click().run()
    assert any("Supply the target month" in w.value for w in app.warning)
    assert all(b.label != "Confirm multi-month plan" for b in app.button)


def test_reviews_are_disabled_by_default_and_need_confirmed_date():
    app = AppTest.from_string("""
from ui.budget_continuity import render_review_preferences
class Client:
    def get_review_preferences(self, user): return {'enabled': False, 'cadence': 'monthly', 'next_review_on': None}
    def get_due_review(self, user): return {'enabled': False, 'due': False}
    def save_review_preferences(self, *args): raise AssertionError('Unconfirmed preferences')
render_review_preferences(Client(), 'u')
""").run(timeout=30)
    app.button[0].click().run()
    assert not app.exception
    assert app.checkbox[0].value is False
    next(b for b in app.button if b.label == "Save review preferences").click().run()
    assert any("Confirm the preferences" in w.value for w in app.warning)
