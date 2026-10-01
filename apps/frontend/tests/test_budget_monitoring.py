import json
from copy import deepcopy
from datetime import date

from test_budget_simple import Client, control, render

CONFIRM = "This is my actual take-home income and these limits include all my expenses."


def test_saved_budget_opens_with_readable_spending_and_no_editor():
    client = Client()
    client.budget.update(total_limit=2000, total_spent=750)
    client.budget["categories"][0].update(spent_amount=0, remaining_amount=1500)
    client.budget["categories"][1].update(spent_amount=650, remaining_amount=-150)
    app = render(client, edit=False)
    assert not app.exception
    assert not app.number_input
    assert not any(b.label in {"Save budget", "Add category", "Cancel changes"} for b in app.button)
    assert [m.label for m in app.metric] == ["Budgeted", "Spent", "Remaining"]
    assert any("Food — SGD 150.00 over" in w.value for w in app.warning)
    assert any("Without category limits: SGD 100.00" in i.value for i in app.info)
    assert len(app.get("plotly_chart")) == 2
    assert len(app.get("progress")) == 1  # Overall progress only; charts cover categories.
    chart = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert chart["data"][0]["y"] == ["Food", "Housing", "Without category limits"]
    assert chart["data"][0]["x"] == [500, 1500, None]
    assert chart["data"][1]["x"] == [650, 0, 100]
    assert chart["data"][1]["marker"]["color"] == ["#dc2626", "#0d9488", "#d97706"]
    assert not any(e.proto.label in {"Explore a change", "Charts"} for e in app.get("status"))
    assert not any("Show" in c.label for c in app.checkbox)
    assert not any(b.label == "Check this change" for b in app.button)
    assert client.reviews == 0 and client.saved is None and client.compared is None


def test_cancel_restores_categories_amounts_method_and_confirmation():
    client = Client()
    original = deepcopy(client.budget)
    app = render(client)
    control(app.number_input, "Monthly savings allocation (SGD)").set_value(900).run()
    control(app.number_input, "Food (SGD)").set_value(550).run()
    control(app.selectbox, "Budgeting method").set_value("80_20").run()
    control(app.selectbox, "Category to add").set_value("pets").run()
    control(app.button, "Add category").click().run()
    control(app.number_input, "Pets (SGD)").set_value(25).run()
    control(app.button, "Remove Housing").click().run()
    control(app.checkbox, CONFIRM).check().run()
    assert any("Unsaved changes" in i.value for i in app.info)
    control(app.button, "Cancel changes").click().run()
    assert not app.exception and not app.number_input
    assert client.budget == original and client.saved is None
    control(app.button, "Edit budget").click().run()
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 800
    assert control(app.number_input, "Food (SGD)").value == 500
    assert control(app.number_input, "Housing (SGD)").value == 1500
    assert control(app.selectbox, "Budgeting method").value == "flexible"
    assert not any(i.label == "Pets (SGD)" for i in app.number_input)
    assert not control(app.checkbox, CONFIRM).value
    assert control(app.button, "Save budget").disabled


def test_custom_add_normalizes_names_prevents_duplicates_and_requires_explicit_amount():
    app = render(Client())
    control(app.selectbox, "Category to add").set_value("Custom category").run()
    control(app.text_input, "Custom category name").set_value("  FOOD ")
    control(app.button, "Add category").click().run()
    assert any("already in your plan" in w.value for w in app.warning)
    assert len([i for i in app.number_input if i.label == "Food (SGD)"]) == 1
    control(app.text_input, "Custom category name").set_value("  Pet   care ")
    control(app.button, "Add category").click().run()
    assert not app.exception
    assert control(app.number_input, "Pet Care (SGD)").value is None
    assert control(app.button, "Save budget").disabled
    assert any("monthly limit for Pet Care" in c.value for c in app.caption)
    control(app.number_input, "Pet Care (SGD)").set_value(0).run()
    assert not control(app.button, "Save budget").disabled


def test_legacy_unsaved_draft_can_be_reviewed_and_cancelled_without_saving():
    client = Client()
    app = render(client, edit=False)
    app.session_state["budget-edit-draft-u-2026-10-01"] = {
        "currency": "SGD",
        "categories": [
            {"category": r["category"], "limit_amount": r["limit_amount"]}
            for r in client.budget["categories"]
        ],
        "planning": {**client.budget["planning"], "savings_target": 900},
    }
    app.run()
    assert not app.exception
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 900
    assert not control(app.checkbox, CONFIRM).value
    assert control(app.metric, "Budgeted").value == "SGD 2,000.00"
    control(app.button, "Cancel changes").click().run()
    assert not app.number_input and client.saved is None
    control(app.button, "Edit budget").click().run()
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 800


def test_success_closes_editor_and_preserves_month_specific_feedback_after_reruns():
    class SavingClient(Client):
        def save_budget(self, user, payload):
            super().save_budget(user, payload)
            previous = {r["category"]: r["spent_amount"] for r in self.budget["categories"]}
            self.budget = {
                **deepcopy(payload),
                "categories": [
                    {
                        **r,
                        "spent_amount": previous.get(r["category"], 0),
                        "remaining_amount": r["limit_amount"] - previous.get(r["category"], 0),
                    }
                    for r in payload["categories"]
                ],
            }
            return self.budget

    client = SavingClient()
    app = render(client)
    control(app.number_input, "Food (SGD)").set_value(550).run()
    control(app.checkbox, CONFIRM).check()
    control(app.button, "Save budget").click().run()
    assert not app.exception and not app.number_input
    assert any(s.value == "Budget saved for October 2026." for s in app.success)
    assert control(app.metric, "Budgeted").value == "SGD 2,050.00"
    app.run()
    assert any(s.value == "Budget saved for October 2026." for s in app.success)
    app.session_state["active_period"] = date(2026, 11, 1)
    app.run()
    assert not app.success
    assert control(app.number_input, "Housing (SGD)").value is None


def test_empty_saved_limits_and_zero_limits_still_show_spending():
    client = Client(planned=False)
    client.budget.update(categories=[], total_spent=50, total_limit=0)
    app = render(client, edit=False)
    assert not app.exception
    assert control(app.metric, "Over budget").value == "SGD 50.00"
    assert len(app.get("plotly_chart")) == 1
    chart = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert chart["data"][0]["x"] == [None]
    assert chart["data"][1]["x"] == [50]
    assert any("positive category limit" in i.value for i in app.info)
    client.budget.update(
        categories=[
            {
                "category": "food",
                "limit_amount": 0,
                "spent_amount": 50,
                "remaining_amount": -50,
            }
        ]
    )
    app.run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 1
    assert any(c.value == "Zero limits: Food." for c in app.caption)
    assert any("SGD 50.00 over" in w.value for w in app.warning)


def test_category_cap_and_empty_editor_give_actionable_save_reasons():
    client = Client(planned=False)
    client.budget["categories"] = [
        {"category": f"category {i}", "limit_amount": 1, "spent_amount": 0, "remaining_amount": 1}
        for i in range(50)
    ]
    app = render(client)
    assert not app.exception
    control(app.selectbox, "Category to add").set_value("food").run()
    assert control(app.button, "Add category").disabled
    assert any("50-category limit reached" in c.value for c in app.caption)
    control(app.button, "Remove Category 0").click().run()
    assert not control(app.button, "Add category").disabled

    small = render(Client(planned=False))
    control(small.button, "Remove Housing").click().run()
    control(small.button, "Remove Food").click().run()
    assert control(small.button, "Save budget").disabled
    assert any("Add at least one category" in c.value for c in small.caption)
