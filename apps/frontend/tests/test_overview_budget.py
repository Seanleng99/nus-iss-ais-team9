import json

import pytest
from streamlit.testing.v1 import AppTest


def render(budget):
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.pages import _render_overview_budget\n"
        "_render_overview_budget(st.session_state['test_budget'], 'SGD')"
    )
    app.session_state["test_budget"] = budget
    return app.run(timeout=30)


@pytest.mark.parametrize("budget", [None, {"categories": []}])
def test_overview_budget_empty_state(budget):
    app = render(budget)
    assert not app.exception
    assert "No category limits" in app.info[0].value
    assert app.button[0].label == "Set up budget"
    assert not app.get("plotly_chart")


@pytest.mark.parametrize(
    "spent,remaining,ring",
    [
        (400, "SGD 500.00", [400, 500, 0]),
        (1000, "SGD 100.00", [900, 0, 100]),
    ],
)
def test_overview_budget_prioritizes_custom_categories_and_includes_all_spending(
    spent, remaining, ring
):
    app = render(
        {
            "currency": "SGD",
            "total_limit": 900,
            "total_spent": spent,
            "categories": [
                {"category": "pet care", "limit_amount": 100, "spent_amount": 120},
                {"category": "housing", "limit_amount": 500, "spent_amount": 100},
                {"category": "groceries", "limit_amount": 100, "spent_amount": 90},
                {"category": "transport", "limit_amount": 100, "spent_amount": 0},
                {"category": "subscriptions", "limit_amount": 0, "spent_amount": 20},
                {"category": "hobbies", "limit_amount": 100, "spent_amount": 10},
            ],
        }
    )
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Spent"] == f"SGD {spent:,.2f}"
    assert metrics["Remaining" if spent < 900 else "Over budget"] == remaining
    assert "categories without budget limits" in app.info[0].value
    assert "2 categories are over" in app.warning[0].value
    assert app.text[0].value.startswith("Subscriptions · Over by")
    assert app.text[1].value.startswith("Pet Care · Over by")
    assert len(app.text) == 5
    assert any("View all 6 categories" in item.value for item in app.caption)
    chart = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert chart["data"][0]["values"] == ring


def test_overview_zero_budget_does_not_divide_by_zero():
    app = render(
        {
            "total_limit": 0,
            "total_spent": 20,
            "categories": [{"category": "pet care", "limit_amount": 0, "spent_amount": 20}],
        }
    )
    assert not app.exception
    assert not app.get("plotly_chart")
    assert any("All category limits are zero" in item.value for item in app.info)
    assert app.text[0].value == "Pet Care · Over by SGD 20.00"


def test_overview_shortcut_opens_registered_budget_page():
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.pages import _render_overview_budget, budget_page\n"
        "class Client:\n"
        "    def get_budget(self, user_id, period): return None\n"
        "st.session_state['backend_client'] = Client()\n"
        "def overview(): _render_overview_budget(None, 'SGD')\n"
        "navigation = st.navigation([st.Page(overview, default=True), "
        "st.Page(budget_page, title='Budget', url_path='budget')])\n"
        "navigation.run()"
    ).run(timeout=30)
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert app.multiselect[0].label == "Budget categories"
