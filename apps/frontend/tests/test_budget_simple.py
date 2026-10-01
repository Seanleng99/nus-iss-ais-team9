from copy import deepcopy
from datetime import date

from streamlit.testing.v1 import AppTest

PERIOD = date(2026, 10, 1)


class Client:
    def __init__(self, planned=True):
        self.saved = None
        self.compared = None
        self.previewed = None
        self.confirmed = None
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
        self.compared = deepcopy(payload)
        # Validate the public extraction contract does not receive saved-record metadata.
        assert "version" not in payload["planning"]
        base = deepcopy(payload)
        candidate = deepcopy(base)
        changes = candidate.pop("scenarios")[0]
        for key in ["savings_target", "take_home_income"]:
            if key in changes:
                candidate["planning"][key] = changes[key]
        for changed in changes.get("categories", []):
            next(c for c in candidate["categories"] if c["category"] == changed["category"])[
                "limit_amount"
            ] = changed["limit_amount"]
        results = []
        for name, draft in [("Current plan", base), ("Proposed change", candidate)]:
            total = sum(c["limit_amount"] for c in draft["categories"])
            balance = (
                draft["planning"]["take_home_income"] - total - draft["planning"]["savings_target"]
            )
            results.append(
                {
                    "name": name,
                    "draft": draft,
                    "totals": {
                        "expense_total": total,
                        "unallocated": max(balance, 0),
                        "funding_gap": max(-balance, 0),
                    },
                    "questions": [],
                }
            )
        return {"results": results, "saved": False}

    def preview_budget_months(self, user, payload):
        self.previewed = deepcopy(payload)
        return {
            "preview_id": "copy",
            "ready": True,
            "questions": [],
            "warnings": [],
            "plans": [
                {
                    "budget": self.budget,
                    "expenses": 2000,
                }
            ],
        }

    def confirm_budget_months(self, user, identifier):
        self.confirmed = identifier
        return {"periods": ["2026-11-01"]}

    def get_budget_commitments(self, user, period):
        return {"policy": {"category_floors": {"food": 400}, "protected_categories": []}}

    def preview_workspace_change(self, user, operation, payload):
        self.previewed = {"operation": operation, **deepcopy(payload)}
        return {"preview_id": "fixed", "target": {**payload, "category_floors": {"food": 400}}}

    def confirm_workspace_change(self, user, identifier):
        self.confirmed = identifier
        return {"saved": True}


def control(items, label):
    return next(item for item in items if item.label == label)


def render(client):
    app = AppTest.from_string("from ui.pages import budget_page\nbudget_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "u"
    app.session_state["active_period"] = PERIOD
    return app.run(timeout=30)


def test_everyday_page_has_no_specialist_setup_and_one_plan_confirmation():
    client = Client()
    app = render(client)
    assert not app.exception
    headings = [s.value for s in app.subheader]
    assert (
        headings.index("Your plan")
        < headings.index("Spending this month")
        < headings.index("Explore a change")
    )
    assert control(app.selectbox, "Planning option").value == "Choose an option"
    assert not any(i.label == "Minimum monthly savings (SGD)" for i in app.number_input)
    assert not any(
        i.label == "Reserve this month's full savings allocation on" for i in app.date_input
    )
    assert client.reviews == 1
    control(app.number_input, "Monthly savings allocation (SGD)").set_value(900).run()
    assert client.reviews == 1  # Pure editor changes do not repeatedly fetch records.
    assert control(app.metric, "Unallocated income").value == "SGD 100.00"
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
    control(app.button, "Save budget").click().run()
    assert client.saved["planning"] is None
    client.saved = None
    control(app.checkbox, "Include take-home income and savings").check().run()
    assert control(app.number_input, "Monthly take-home income (SGD)").value is None
    assert control(app.number_input, "Monthly savings allocation (SGD)").value is None
    control(app.button, "Save budget").click().run()
    assert client.saved is None


def test_simple_comparison_does_not_save_and_hides_obsolete_results():
    client = Client()
    app = render(client)
    control(app.selectbox, "What would you like to change?").set_value("Savings").run()
    control(app.number_input, "New monthly savings (SGD)").set_value(1100).run()
    control(app.button, "Check this change").click().run()
    assert not app.exception
    assert any("shortfall of SGD 100.00" in w.value for w in app.warning)
    assert client.saved is None
    control(app.number_input, "New monthly savings (SGD)").set_value(900).run()
    assert not any(b.label == "Review this change in my plan" for b in app.button)
    control(app.button, "Check this change").click().run()
    control(app.button, "Review this change in my plan").click().run()
    assert client.saved is None
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 900
    control(app.button, "Save budget").click().run()
    assert client.saved is None


def test_copy_next_month_requires_preview_and_explicit_coverage_confirmation():
    client = Client()
    app = render(client)
    control(app.button, "Use this plan next month").click().run()
    control(app.button, "Preview next month's plan").click().run()
    assert not app.exception
    assert client.previewed["first_period"] == "2026-11-01"
    assert client.previewed["carry_rule"] == "copy_limits"
    assert client.previewed["allow_overwrite"] is False
    assert control(app.button, "Confirm next month's plan").disabled
    control(
        app.checkbox,
        "These are my actual income, savings and complete expense limits for November 2026.",
    ).check().run()
    assert not control(app.button, "Confirm next month's plan").disabled
    control(app.number_input, "Next month's savings (SGD)").set_value(900).run()
    assert not any(b.label == "Confirm next month's plan" for b in app.button)
    assert client.confirmed is None


def test_fixed_amount_action_sends_only_the_selected_setting_and_requires_confirmation():
    client = Client()
    app = render(client)
    control(app.selectbox, "Planning option").set_value("Fixed amounts").run()
    control(app.multiselect, "Keep these category amounts fixed").set_value(["housing"]).run()
    control(app.button, "Preview fixed amounts").click().run()
    assert not app.exception
    assert client.previewed == {
        "operation": "commitments",
        "period_start": str(PERIOD),
        "protected_categories": ["housing"],
    }
    assert client.confirmed is None
    control(app.button, "Confirm changes").click().run()
    assert client.confirmed == "fixed"
