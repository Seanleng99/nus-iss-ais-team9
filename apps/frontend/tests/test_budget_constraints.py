from streamlit.testing.v1 import AppTest


def test_commitments_require_user_inputs_and_confirmation():
    app = AppTest.from_string("""
from datetime import date
from ui.budget_constraints import render_commitments
class Client:
    def get_budget_commitments(self, user, period): return {}
    def get_cashflow_settings(self, user): return {}
    def list_goals(self, user): return []
    def save_budget_commitments(self, *args): raise AssertionError('Unconfirmed save')
render_commitments(Client(), 'u', date(2026,10,1), {'food': 500}, 'draft')
""").run(timeout=30)
    app.button[0].click().run()
    assert not app.exception
    next(item for item in app.button if item.label == "Save commitments").click().run()
    assert any("Enter the savings minimum" in warning.value for warning in app.warning)
