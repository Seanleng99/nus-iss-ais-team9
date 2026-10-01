import pytest
from test_budget_simple import Client, control, render

CONFIRMATION = "This is my actual take-home income and these limits include all my expenses."


@pytest.mark.parametrize("method", ["flexible", "80_20", "pay_yourself_first", "zero_based"])
def test_method_choice_is_inline_and_does_not_change_amounts_or_save(method):
    client = Client()
    app = render(client)
    assert control(app.selectbox, "Budgeting method").value == "flexible"
    control(app.selectbox, "Budgeting method").set_value(method).run()
    assert not app.exception
    assert not any("(%)" in widget.label for widget in app.number_input)
    assert not any("essential costs" in widget.label for widget in app.multiselect)
    assert control(app.number_input, "Monthly savings allocation (SGD)").value == 800
    assert control(app.number_input, "Housing (SGD)").value == 1500
    assert client.saved is None and client.compared is None
    if method == "zero_based":
        assert control(app.button, "Save budget").disabled
        control(app.number_input, "Monthly savings allocation (SGD)").set_value(1000).run()
    control(app.checkbox, CONFIRMATION).check()
    control(app.button, "Save budget").click().run()
    assert client.saved["planning"]["method"] == {"name": method, "category_groups": {}}


def test_custom_split_requires_explicit_complete_percentages_and_category_groups():
    client = Client()
    app = render(client)
    control(app.selectbox, "Budgeting method").set_value("custom").run()
    assert control(app.number_input, "Needs (%)").value is None
    assert control(app.number_input, "Wants (%)").value is None
    assert control(app.number_input, "Savings (%)").value is None
    assert control(app.button, "Save budget").disabled
    for label, value in [("Needs (%)", 60), ("Wants (%)", 20), ("Savings (%)", 10)]:
        control(app.number_input, label).set_value(value)
    control(app.multiselect, "Needs (essential costs)").set_value(["housing"])
    control(app.multiselect, "Wants (optional spending)").set_value(["food"]).run()
    assert control(app.button, "Save budget").disabled
    assert not any("Monthly guide:" in c.value for c in app.caption)
    control(app.number_input, "Savings (%)").set_value(20).run()
    assert not control(app.button, "Save budget").disabled
    assert any("Needs SGD 1,800.00" in c.value for c in app.caption)
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    control(app.checkbox, CONFIRMATION).check()
    control(app.button, "Save budget").click().run()
    assert client.saved["planning"]["method"] == {
        "name": "custom",
        "percentages": {"needs": 60, "wants": 20, "savings": 20},
        "category_groups": {"housing": "needs", "food": "wants"},
    }
    assert client.saved["planning"]["savings_target"] == 800  # Guide never overwrites inputs.


def test_needs_and_wants_must_be_complete_and_disjoint_without_inferred_groups():
    client = Client()
    app = render(client)
    control(app.selectbox, "Budgeting method").set_value("50_30_20").run()
    assert control(app.multiselect, "Needs (essential costs)").value == []
    assert control(app.multiselect, "Wants (optional spending)").value == []
    assert control(app.button, "Save budget").disabled
    control(app.multiselect, "Needs (essential costs)").set_value(["housing", "food"])
    control(app.multiselect, "Wants (optional spending)").set_value(["food"]).run()
    assert control(app.button, "Save budget").disabled
    control(app.multiselect, "Needs (essential costs)").set_value(["housing"]).run()
    assert not control(app.button, "Save budget").disabled
    assert not any("(%)" in widget.label for widget in app.number_input)
    control(app.checkbox, CONFIRMATION).check()
    control(app.button, "Save budget").click().run()
    assert client.saved["planning"]["method"]["category_groups"] == {
        "housing": "needs", "food": "wants",
    }


def test_switching_method_clears_inapplicable_fields_and_invalidates_confirmation_and_comparison():
    client = Client()
    client.budget["planning"]["method"] = {
        "name": "custom",
        "percentages": {"needs": 60, "wants": 20, "savings": 20},
        "category_groups": {"housing": "needs", "food": "wants"},
    }
    app = render(client)
    control(app.checkbox, CONFIRMATION).check().run()
    control(app.selectbox, "What would you like to change?").set_value("Savings").run()
    control(app.number_input, "New monthly savings (SGD)").set_value(900).run()
    control(app.button, "Check this change").click().run()
    assert any(b.label == "Review this change in my plan" for b in app.button)
    control(app.selectbox, "Budgeting method").set_value("flexible").run()
    assert not app.exception
    assert not control(app.checkbox, CONFIRMATION).value
    assert not any(b.label == "Review this change in my plan" for b in app.button)
    assert not any("(%)" in widget.label for widget in app.number_input)
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    control(app.checkbox, CONFIRMATION).check()
    control(app.button, "Save budget").click().run()
    assert client.saved["planning"]["method"] == {"name": "flexible", "category_groups": {}}
