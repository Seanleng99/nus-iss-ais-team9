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
        "    def review_budget(self, user_id, period): return None\n"
        "st.session_state['backend_client'] = Client()\n"
        "def overview(): _render_overview_budget(None, 'SGD')\n"
        "navigation = st.navigation([st.Page(overview, default=True), "
        "st.Page(budget_page, title='Budget', url_path='budget')])\n"
        "navigation.run()"
    ).run(timeout=30)
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert any(item.label == "Category to add" for item in app.selectbox)
    assert any(item.value == "Create your budget" for item in app.subheader)

def test_planned_budget_summary_keeps_savings_separate_from_spending():
    app = render({
        "currency": "SGD", "total_limit": 3000, "total_spent": 500,
        "categories": [{"category": "housing", "limit_amount": 3000, "spent_amount": 500}],
        "planning": {"take_home_income": 4000, "savings_target": 800},
    })
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Planned"] == "SGD 3,000.00"
    assert metrics["Savings allocation"] == "SGD 800.00"
    assert metrics["Unallocated income"] == "SGD 200.00"


@pytest.mark.parametrize("spent", [750, 2600, 2600.01, 6000])
def test_overview_category_overage_does_not_claim_the_total_budget_is_exceeded(spent):
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.pages import dashboard_page\n"
        "class Client:\n"
        "    def get_dashboard(self, user, period): return st.session_state['dashboard']\n"
        "st.session_state['backend_client'] = Client()\n"
        "dashboard_page()"
    )
    app.session_state["dashboard"] = {
        "currency": "SGD", "monthly_income": 5000, "total_spent": spent,
        "available_balance": 5000 - spent, "savings_rate_percent": 0,
        "budget_alert": {
            "status": "over", "over_income": spent > 5000, "over_budget": True,
            "total_spent": spent, "monthly_income": 5000, "total_budget_limit": 2600,
            "amount_over_income": max(0, spent - 5000),
            "categories_over": [{"category": "food", "spent": 650, "limit_amount": 600}],
        },
    }
    app.run(timeout=30)
    assert not app.exception
    total_errors = [item.value for item in app.error if "over your monthly budget" in item.value]
    assert bool(total_errors) is (spent > 2600)
    if spent <= 2600:
        assert any("Food: SGD 50.00 over its limit" in item.value for item in app.warning)
    else:
        assert "Food" in total_errors[0]
    assert any("more than your monthly income" in item.value for item in app.error) is (spent > 5000)
