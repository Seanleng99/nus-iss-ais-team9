from copy import deepcopy
from datetime import date

from streamlit.testing.v1 import AppTest


class Client:
    def __init__(self):
        self.saved = None
        self.compared = None

    def review_budget(self, user, period):
        return None

    def get_budget(self, user, period):
        return {
            "currency": "SGD",
            "planning": {
                "take_home_income": 4000,
                "income_basis": "take_home",
                "savings_target": 800,
                "expenses_confirmed": True,
                "version": "budget-planning-v1",
            },
            "categories": [
                {
                    "category": "housing",
                    "limit_amount": 3000,
                    "spent_amount": 500,
                    "remaining_amount": 2500,
                }
            ],
        }

    def compare_budget(self, user, payload):
        self.compared = deepcopy(payload)
        results = []
        for name in ("Current plan", "Alternative"):
            candidate = deepcopy(payload)
            candidate["action"] = "plan"
            candidate["scenarios"] = []
            if name == "Alternative":
                candidate["planning"]["savings_target"] = payload["scenarios"][0]["savings_target"]
            results.append(
                {
                    "name": name,
                    "draft": candidate,
                    "totals": {
                        "expense_total": 3000,
                        "unallocated": 4000 - 3000 - candidate["planning"]["savings_target"],
                        "funding_gap": 0,
                    },
                    "method": {
                        "label": "Savings first",
                        "targets": {"savings": candidate["planning"]["savings_target"]},
                        "warnings": [],
                    },
                    "questions": ["Confirm expense coverage."],
                }
            )
        return {"results": results, "questions": [], "saved": False}

    def save_budget(self, user, payload):
        self.saved = payload


def render(client):
    app = AppTest.from_string("from ui.pages import budget_page\nbudget_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "u"
    app.session_state["active_period"] = date(2026, 10, 1)
    app.run(timeout=30)
    control(app.selectbox, "Planning option").set_value("Budgeting methods").run()
    return app


def control(items, label):
    return next(item for item in items if item.label == label)


def test_compare_then_adopt_keeps_saving_explicit_and_requires_actual_income():
    client = Client()
    app = render(client)
    control(app.selectbox, "Budgeting method").set_value("pay_yourself_first").run()
    control(app.number_input, "Alternative savings (SGD)").set_value(1000)
    control(app.button, "Compare scenarios").click().run()
    assert not app.exception
    assert client.saved is None
    assert client.compared["planning"]["method"]["name"] == "pay_yourself_first"
    assert len(app.get("plotly_chart")) == 3
    control(app.selectbox, "Option to adopt").set_value("Alternative").run()
    control(app.button, "Use option in editor").click().run()
    assert not app.exception
    assert client.saved is None
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 1000
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    assert any("actual take-home" in item.value for item in app.warning)
    control(
        app.checkbox, "This is my actual take-home income and these limits include all my expenses.",
    ).check()
    control(app.button, "Save budget").click().run()
    assert not app.exception
    assert client.saved["planning"]["savings_target"] == 1000
    assert client.saved["planning"]["method"]["name"] == "pay_yourself_first"
    assert client.saved["planning"]["income_basis"] == "take_home"


def test_changing_exploration_inputs_invalidates_displayed_comparison():
    client = Client()
    app = render(client)
    control(app.number_input, "Alternative savings (SGD)").set_value(1000)
    control(app.button, "Compare scenarios").click().run()
    assert any(item.label == "Use option in editor" for item in app.button)
    control(app.number_input, "Alternative savings (SGD)").set_value(900).run()
    assert not any(item.label == "Use option in editor" for item in app.button)
    assert client.saved is None


def test_custom_percentages_start_unknown_and_require_all_three_inputs():
    client = Client()
    app = render(client)
    control(app.selectbox, "Budgeting method").set_value("custom").run()
    assert control(app.number_input, "Needs percentage").value is None
    assert control(app.selectbox, "Classify housing").value == "Choose"
    control(app.button, "Compare scenarios").click().run()
    assert client.compared is None
    assert any("all three custom percentages" in item.value for item in app.warning)


def test_alternative_custom_method_has_its_own_percentages_and_classification():
    client = Client()
    app = render(client)
    control(app.selectbox, "Alternative method").set_value("custom").run()
    assert control(app.number_input, "Alternative Needs percentage").value is None
    control(app.number_input, "Alternative Needs percentage").set_value(60)
    control(app.number_input, "Alternative Wants percentage").set_value(20)
    control(app.number_input, "Alternative Savings percentage").set_value(20)
    control(app.number_input, "Alternative savings (SGD)").set_value(800)
    control(app.selectbox, "Alternative Classify housing").set_value("needs")
    control(app.button, "Compare scenarios").click().run()
    assert not app.exception
    assert client.compared["scenarios"][0]["method"] == {
        "name": "custom",
        "percentages": {"needs": 60, "wants": 20, "savings": 20},
        "category_groups": {"housing": "needs"},
    }
    assert client.compared["planning"]["method"]["name"] == "flexible"
