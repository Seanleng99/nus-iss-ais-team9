from copy import deepcopy
from datetime import date

from streamlit.testing.v1 import AppTest

PERIOD = date(2026, 10, 1)


class Client:
    def __init__(self, planned=True):
        self.saved = None
        self.compared = None
        self.reviews = 0
        self.budget = {
            "currency": "SGD",
            "categories": [
                {
                    "category": "housing",
                    "limit_amount": 1500,
                    "spent_amount": 600,
                    "remaining_amount": 900,
                },
                {
                    "category": "food",
                    "limit_amount": 500,
                    "spent_amount": 100,
                    "remaining_amount": 400,
                },
            ],
        }
        if planned:
            self.budget["planning"] = {
                "take_home_income": 3000,
                "savings_target": 800,
                "income_basis": "take_home",
                "expenses_confirmed": True,
                "version": "budget-planning-v4",
            }

    def get_budget(self, user, period):
        return self.budget if period == PERIOD else None

    def review_budget(self, user, period):
        self.reviews += 1

    def save_budget(self, user, payload):
        self.saved = deepcopy(payload)

    def compare_budget(self, user, payload):
        raise AssertionError("Budget comparisons belong in Coach")



def control(items, label):
    return next(item for item in items if item.label == label)


def render(client, *, edit=True):
    app = AppTest.from_string("from ui.pages import budget_page\nbudget_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "u"
    app.session_state["active_period"] = PERIOD
    app.run(timeout=30)
    if edit and any(b.label == "Edit budget" for b in app.button):
        control(app.button, "Edit budget").click().run()
    return app


def test_everyday_page_has_no_specialist_setup_and_one_plan_confirmation():
    client = Client()
    app = render(client)
    assert not app.exception
    headings = [s.value for s in app.subheader]
    assert (
        headings.index("Edit budget") < headings.index("Spending this month")
    )
    assert not any(item.label == "Planning option" for item in app.selectbox)
    assert not any(item.label == "More planning options" for item in app.expander)
    assert not any(i.label == "Minimum monthly savings (SGD)" for i in app.number_input)
    assert not any(
        i.label == "Reserve this month's full savings allocation on" for i in app.date_input
    )
    assert client.reviews == 0
    control(app.number_input, "Monthly savings allocation (SGD)").set_value(900).run()
    assert client.reviews == 0  # Ordinary Budget rendering never calls the Coach review tool.
    assert control(app.metric, "Left to allocate").value == "SGD 100.00"
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    control(
        app.checkbox, "This is my actual take-home income and these limits include all my expenses."
    ).check()
    control(app.button, "Save budget").click().run()
    assert client.saved["planning"]["savings_target"] == 900


def test_legacy_category_tracking_does_not_need_income_and_new_plan_inputs_start_unknown():
    client = Client(planned=False)
    app = render(client)
    control(app.number_input, "Food (SGD)").set_value(550).run()
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    control(app.checkbox, "I have reviewed these category limits for October 2026.").check()
    control(app.button, "Save budget").click().run()
    assert client.saved["planning"] is None
    client.saved = None
    control(app.checkbox, "Include take-home income and savings").check().run()
    assert control(app.number_input, "Monthly take-home income (SGD)").value is None
    assert control(app.number_input, "Monthly savings allocation (SGD)").value is None
    control(app.button, "Save budget").click().run()
    assert client.saved is None


def test_saved_method_survives_direct_edit_and_confirmed_save():
    client = Client()
    method = {
        "name": "custom",
        "percentages": {"needs": 60, "wants": 20, "savings": 20},
        "category_groups": {"housing": "needs", "food": "wants"},
    }
    client.budget["planning"]["method"] = deepcopy(method)
    app = render(client)
    assert not app.exception
    assert control(app.selectbox, "Budgeting method").value == "custom"
    control(app.number_input, "Monthly savings allocation (SGD)").set_value(900).run()
    assert client.saved is None
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    control(
        app.checkbox, "This is my actual take-home income and these limits include all my expenses."
    ).check()
    control(app.button, "Save budget").click().run()
    assert not app.exception
    assert client.saved["planning"]["method"] == method
    assert client.saved["planning"]["savings_target"] == 900
