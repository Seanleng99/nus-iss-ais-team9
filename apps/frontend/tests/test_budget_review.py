from copy import deepcopy
from datetime import date

from streamlit.testing.v1 import AppTest


class Client:
    def __init__(self):
        self.saved = None
        self.reviews = 0

    def get_budget(self, user, period):
        return {
            "currency": "SGD",
            "planning": {
                "take_home_income": 2000,
                "savings_target": 500,
                "income_basis": "take_home",
                "expenses_confirmed": True,
            },
            "categories": [
                {
                    "category": "food",
                    "limit_amount": 100,
                    "spent_amount": 150,
                    "remaining_amount": -50,
                }
            ],
        }

    def review_budget(self, user, period):
        self.reviews += 1
        return {
            "as_of": "2026-09-15",
            "phase": "current",
            "total_spent": 150,
            "total_pace_estimate": None,
            "unbudgeted_spent": 0,
            "has_budget": True,
            "warnings": ["Pace is an illustration. Records may be incomplete."],
            "categories": [
                {
                    "category": "food",
                    "limit_amount": 100,
                    "spent": 150,
                    "remaining": -50,
                    "status": "over",
                    "pace_estimate": None,
                    "pace_note": "Insufficient activity days",
                    "remaining_per_day": 0,
                }
            ],
            "suggestions": [
                {
                    "category": "food",
                    "proposed_limit": 150,
                    "reason": "Cover recorded spending only.",
                }
            ],
            "evidence_fingerprint": "a" * 64,
            "comparison": {
                "results": [
                    {
                        "name": "Cover recorded spending",
                        "totals": {"funding_gap": 0},
                        "questions": ["Confirm all expenses are included."],
                        "draft": {
                            "period_start": period.isoformat(),
                            "currency": "SGD",
                            "action": "plan",
                            "categories": [{"category": "food", "limit_amount": 150}],
                            "planning": {
                                "take_home_income": 2000,
                                "savings_target": 500,
                                "income_basis": "take_home",
                                "expenses_confirmed": False,
                            },
                        },
                    }
                ]
            },
        }

    def save_budget(self, user, payload):
        self.saved = deepcopy(payload)


def control(items, label):
    return next(item for item in items if item.label == label)


def test_review_loads_automatically_and_adoption_requires_actual_income_and_coverage():
    client = Client()
    app = AppTest.from_string("from ui.pages import budget_page\nbudget_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "u1"
    app.session_state["active_period"] = date(2026, 9, 1)
    app.run(timeout=30)
    assert not app.exception
    assert client.reviews == 1
    control(app.button, "Refresh spending review").click().run()
    assert not app.exception
    assert client.reviews == 2 and client.saved is None
    assert control(app.metric, "Month-end pace illustration").value == "Unavailable"
    assert len(app.get("plotly_chart")) == 2
    control(app.checkbox, "Show suggested adjustment").check().run()
    control(app.button, "Review adjustment in editor").click().run()
    assert not app.exception
    assert control(app.number_input, "Food (SGD)").value == 150
    assert client.saved is None
    control(app.button, "Save budget").click().run()
    assert client.saved is None
    control(
        app.checkbox, "This is my actual take-home income and these limits include all my expenses.",
    ).check()
    control(app.button, "Save budget").click().run()
    assert not app.exception
    assert client.saved["review_evidence"] == "a" * 64
    assert client.saved["categories"] == [{"category": "food", "limit_amount": 150}]
    assert client.saved["planning"]["savings_target"] == 500
