from test_budget_simple import Client, control, render


class SpendingClient(Client):
    def __init__(self):
        super().__init__()
        self.budget.update(total_limit=2000, total_spent=800)
        self.budget["categories"][0].update(spent_amount=50, remaining_amount=1450)
        self.budget["categories"][1].update(spent_amount=650, remaining_amount=-150)

    def review_budget(self, user, period):
        raise AssertionError("Budget must not generate a Coach review or adjustment")

    def preview_budget_months(self, user, payload):
        raise AssertionError("Budget must not prepare a next-month copy")

    def confirm_budget_months(self, user, identifier):
        raise AssertionError("Budget must not save a next-month copy")


def test_budget_keeps_spending_facts_without_copy_pace_or_automatic_adjustments():
    client = SpendingClient()
    app = render(client)
    assert not app.exception
    assert next(m.value for m in app.metric if m.label.endswith("Spent")) == "SGD 800.00"
    assert next(m.value for m in app.metric if m.label.endswith("Remaining")) == "SGD 1,200.00"
    assert any("Food" in w.value for w in app.warning)
    assert any("SGD 100.00" in c.value and "without limits" in c.value for c in app.caption)
    assert any("not an available bank balance" in c.value for c in app.caption)
    labels = {item.label for items in (app.button, app.checkbox, app.metric) for item in items}
    assert labels.isdisjoint({
        "Use this plan next month", "Refresh spending review", "Show category and pace details",
        "Month-end pace illustration", "Show suggested adjustment", "Review adjustment in editor",
    })
    assert len(app.get("plotly_chart")) == 1
    control(app.checkbox, "Show budget allocation").check().run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2
    assert control(app.number_input, "Food (SGD)").value == 500
    assert client.saved is None
    control(app.number_input, "Food (SGD)").set_value(550).run()
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    control(app.checkbox, "This is my actual take-home income and these limits include all my expenses.").check()
    control(app.button, "Save budget").click().run()
    assert not app.exception
    assert next(c["limit_amount"] for c in client.saved["categories"] if c["category"] == "food") == 550
    assert client.saved["planning"]["savings_target"] == 800
