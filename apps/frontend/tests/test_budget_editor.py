import httpx
from test_budget_method_choice import CONFIRMATION
from test_budget_simple import Client, control, render


def table_with(app, column):
    return next(table.value for table in app.table if column in table.value.columns)


def test_summary_updates_and_any_plan_amount_change_needs_fresh_confirmation():
    client = Client()
    app = render(client)
    assert [m.label for m in app.metric][:4] == ["Income", "Expenses", "Savings", "Left to allocate"]
    control(app.checkbox, CONFIRMATION).check().run()
    control(app.number_input, "Food (SGD)").set_value(600).run()
    assert control(app.metric, "Expenses").value == "SGD 2,100.00"
    assert control(app.metric, "Left to allocate").value == "SGD 100.00"
    assert not control(app.checkbox, CONFIRMATION).value
    review = table_with(app, "Change")
    assert review.to_dict("records") == [{"Change": "Food", "Saved": "SGD 500.00", "This plan": "SGD 600.00"}]
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    assert control(app.number_input, "Food (SGD)").value == 600
    assert len(app.get("plotly_chart")) == 1


def test_custom_category_is_blank_and_validation_keeps_editor_and_spending_visible():
    client = Client()
    app = render(client)
    control(app.multiselect, "Budget categories").set_value(["housing", "food", "pet care"]).run()
    assert not app.exception
    assert control(app.number_input, "Pet Care (SGD)").value is None
    assert control(app.metric, "Expenses").value == "Not entered"
    assert control(app.metric, "Left to allocate").value == "Enter missing amounts"
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    assert any("monthly limit for: Pet Care" in w.value for w in app.warning)
    assert len(app.get("plotly_chart")) == 1
    control(app.number_input, "Pet Care (SGD)").set_value(100).run()
    control(app.checkbox, CONFIRMATION).check()
    control(app.button, "Save budget").click().run()
    assert client.saved["categories"][-1] == {"category": "pet care", "limit_amount": 100}


def test_removing_category_is_reviewed_before_saving_and_does_not_delete_records():
    client = Client()
    app = render(client)
    control(app.multiselect, "Budget categories").set_value(["housing"]).run()
    review = table_with(app, "Change")
    assert review.to_dict("records") == [{"Change": "Food", "Saved": "SGD 500.00", "This plan": "Remove limit"}]
    assert any("keeps recorded transactions" in c.value for c in app.caption)
    assert client.saved is None
    control(app.checkbox, CONFIRMATION).check()
    control(app.button, "Save budget").click().run()
    assert client.saved["categories"] == [{"category": "housing", "limit_amount": 1500}]
    assert client.budget["categories"][1]["spent_amount"] == 100


def test_suggested_savings_requires_click_then_review_without_changing_categories():
    client = Client()
    app = render(client)
    control(app.selectbox, "Budgeting method").set_value("80_20").run()
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 800
    guide = table_with(app, "Suggested")
    assert guide.to_dict("records")[1] == {"Group": "Savings", "Suggested": "SGD 600.00", "Your plan": "SGD 800.00"}
    control(app.checkbox, CONFIRMATION).check().run()
    control(app.button, "Use suggested savings amount").click().run()
    assert not app.exception
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 600
    assert control(app.number_input, "Housing (SGD)").value == 1500
    assert control(app.number_input, "Food (SGD)").value == 500
    assert not control(app.checkbox, CONFIRMATION).value
    assert client.saved is None


def test_allocation_is_optional_and_change_comparison_shows_editor_current_amounts():
    client = Client()
    app = render(client)
    assert len(app.get("plotly_chart")) == 1
    control(app.checkbox, "Show budget allocation").check().run()
    assert len(app.get("plotly_chart")) == 2
    control(app.number_input, "Monthly savings allocation (SGD)").set_value(900).run()
    control(app.selectbox, "What would you like to change?").set_value("Savings").run()
    control(app.number_input, "New monthly savings (SGD)").set_value(1000).run()
    control(app.button, "Check this change").click().run()
    comparison = table_with(app, "Current").set_index("Item")
    assert comparison.loc["Savings"].to_dict() == {"Current": "SGD 900.00", "Proposed": "SGD 1,000.00"}
    assert comparison.loc["Left to allocate"].to_dict() == {"Current": "SGD 100.00", "Proposed": "SGD 0.00"}
    assert client.saved is None


def test_backend_rejection_explains_problem_and_preserves_values_without_saving():
    class RejectedClient(Client):
        def save_budget(self, user, payload):
            response = httpx.Response(422, json={"detail": [{"loc": ["body", "categories", 1, "limit_amount"], "msg": "Value error, this amount conflicts with your saved minimum."}]}, request=httpx.Request("PUT", "https://example.test/budget"))
            raise httpx.HTTPStatusError("Rejected", request=response.request, response=response)

    client = RejectedClient()
    app = render(client)
    control(app.number_input, "Food (SGD)").set_value(400).run()
    control(app.checkbox, CONFIRMATION).check()
    control(app.button, "Save budget").click().run()
    assert not app.exception
    assert client.saved is None
    assert any("Food: this amount conflicts with your saved minimum" in w.value for w in app.warning)
    assert control(app.number_input, "Food (SGD)").value == 400
    assert len(app.get("plotly_chart")) == 1
    control(app.button, "Save budget").click().run()
    assert not control(app.checkbox, CONFIRMATION).value
    assert control(app.number_input, "Food (SGD)").value == 400
