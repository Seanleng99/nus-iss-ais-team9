from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest


class FakeBackendClient:
    def list_profiles(self) -> list[dict]:
        return [
            {
                "user_id": "alex",
                "display_name": "Alex Lee",
                "monthly_income": {"currency": "SGD", "amount": 6200},
                "risk_tolerance": "growth",
            },
            {
                "user_id": "sam",
                "display_name": "Sam Tan",
                "monthly_income": {"currency": "SGD", "amount": 4800},
                "risk_tolerance": "moderate",
            },
        ]

    def get_dashboard(self, user_id: str, period_start: object) -> None:
        return None


class NoProfilesClient:
    def list_profiles(self) -> list[dict]:
        return []


class SparseProfileClient:
    def __init__(self) -> None:
        self.saved_profile: dict | None = None
        self.deleted_user_id: str | None = None

    def get_profile(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "monthly_income": None,
            "risk_tolerance": None,
            "accessibility_preferences": [],
            "preferences": {},
        }

    def get_fairness_profile(self, user_id: str) -> dict:
        return {
            "consent": {"granted": True},
            "demographics": None,
        }

    def save_profile(self, user_id: str, payload: dict) -> dict:
        self.saved_profile = payload
        return {"user_id": user_id, **payload}

    def delete_profile(self, user_id: str) -> bool:
        self.deleted_user_id = user_id
        return True


class WorkspaceDefaultsClient:
    def get_dashboard(self, user_id: str, period_start: date) -> None:
        return None

    def list_transactions(self, user_id: str, period_start: date) -> list[dict]:
        return [
            {
                "id": "transaction-1",
                "occurred_on": "2026-08-01",
                "description": "Saved transaction",
                "category": "housing",
                "amount": {"currency": "SGD", "amount": 1200},
                "recurring": True,
            }
        ]

    def get_budget(self, user_id: str, period_start: date) -> dict:
        return {
            "categories": [
                {
                    "category": "housing",
                    "limit_amount": 1800,
                    "spent_amount": 1200,
                    "remaining_amount": 600,
                }
            ]
        }

    def list_goals(self, user_id: str) -> list[dict]:
        return [
            {
                "id": "goal-1",
                "name": "Saved goal",
                "target_amount": {"currency": "SGD", "amount": 10000},
                "current_amount": {"currency": "SGD", "amount": 1000},
                "target_months": 12,
            }
        ]


class CoachClient:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def ask_coach(self, payload: dict) -> dict:
        self.questions.append(payload["message"])
        return {"answer": "Start by comparing essential spending with monthly income."}


def test_multipage_app_renders_without_runtime_errors() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = FakeBackendClient()
    app.run(timeout=30)

    assert not app.exception
    assert app.sidebar.selectbox[0].label == "Active profile"
    assert app.sidebar.selectbox[0].options == ["Alex Lee · alex", "Sam Tan · sam"]
    assert app.sidebar.selectbox[1].label == "Period"
    assert app.sidebar.selectbox[1].disabled is False
    assert app.session_state["active_user_id"] == "alex"
    page_links = {item.label: item for item in app.sidebar.get("page_link")}
    assert page_links["Overview"].proto.page == ""


def test_no_profiles_defaults_to_create_profile_and_disables_workspace() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = NoProfilesClient()
    app.session_state["active_user_id"] = "stale-profile"
    app.run(timeout=30)

    assert not app.exception
    assert "active_user_id" not in app.session_state
    assert [item.label for item in app.sidebar.selectbox] == ["Period"]
    assert app.sidebar.selectbox[0].disabled is True

    page_links = {item.label: item for item in app.sidebar.get("page_link")}
    assert page_links["Create profile"].proto.page == ""
    for label in [
        "Profile settings",
        "Overview",
        "Transactions",
        "Budget",
        "Goals",
        "Coach",
    ]:
        assert page_links[label].disabled is True
    assert page_links["Create profile"].disabled is False


def test_sparse_profile_inputs_start_empty_or_zero() -> None:
    app = AppTest.from_string("from ui.pages import profile_page\nprofile_page()")
    app.session_state["backend_client"] = SparseProfileClient()
    app.session_state["active_user_id"] = "sparse-user"
    app.run(timeout=30)

    assert not app.exception
    assert app.text_input[0].label == "Display name"
    assert app.text_input[0].value == ""
    assert [(item.label, item.value) for item in app.number_input] == [
        ("Monthly income (SGD)", 0.0),
        ("Household size", 0),
        ("Dependants", 0),
    ]
    assert all(item.value is None for item in app.selectbox)
    assert [item.value for item in app.multiselect] == [[], []]

    app.button(key="FormSubmitter:profile-Save profile").click().run(timeout=30)
    saved = app.session_state["backend_client"].saved_profile
    assert saved["risk_tolerance"] is None
    assert saved["household_size"] is None
    assert saved["preferences"] == {}


def test_profile_deletion_requires_confirmation() -> None:
    app = AppTest.from_string(
        "from ui.pages import profile_page\nprofile_page()"
    )
    app.session_state["backend_client"] = SparseProfileClient()
    app.session_state["active_user_id"] = "delete-user"
    app.session_state["coach_history"] = [{"role": "user", "content": "hello"}]
    app.run(timeout=30)

    delete_button = app.button(key="delete-profile-delete-user")
    assert not app.exception
    assert delete_button.disabled is True

    app.checkbox(key="delete-profile-confirmed-delete-user").check().run(timeout=30)
    app.button(key="delete-profile-delete-user").click().run(timeout=30)

    assert app.session_state["backend_client"].deleted_user_id == "delete-user"
    assert "active_user_id" not in app.session_state
    assert "coach_history" not in app.session_state
    assert app.session_state["profile_deleted_notice"] == "Profile deleted."
    assert app.session_state["profile_deleted_redirect"] is True


def _workspace_page(source: str) -> AppTest:
    app = AppTest.from_string(f"from ui.pages import {source}\n{source}()")
    app.session_state["backend_client"] = WorkspaceDefaultsClient()
    app.session_state["active_user_id"] = "workspace-user"
    app.session_state["active_period"] = date(2026, 8, 1)
    return app.run(timeout=30)


def test_overview_has_no_unsaved_input_defaults() -> None:
    app = _workspace_page("dashboard_page")

    assert not app.exception
    assert not app.text_input
    assert not app.number_input
    assert not app.selectbox
    assert not app.date_input


def test_transaction_inputs_start_empty_or_zero() -> None:
    app = _workspace_page("transactions_page")

    assert not app.exception
    assert [(item.label, item.value) for item in app.text_input] == [("Description", "")]
    assert {item.label: item.value for item in app.selectbox} == {
        "Category": None,
        "Transaction": None,
    }
    assert [(item.label, item.value) for item in app.number_input] == [("Amount (SGD)", 0.0)]
    assert [(item.label, item.value) for item in app.date_input] == [("Date", None)]
    assert app.toggle[0].value is False


def test_budget_defaults_to_zero_except_saved_values() -> None:
    app = _workspace_page("budget_page")

    assert not app.exception
    values = {item.label: item.value for item in app.number_input}
    assert values["Housing (SGD)"] == 1800.0
    assert all(value == 0.0 for label, value in values.items() if label != "Housing (SGD)")


def test_goal_inputs_start_empty_or_zero() -> None:
    app = _workspace_page("goals_page")

    assert not app.exception
    assert [(item.label, item.value) for item in app.text_input] == [("Goal name", "")]
    assert [(item.label, item.value) for item in app.number_input] == [
        ("Target (SGD)", 0.0),
        ("Saved (SGD)", 0.0),
        ("Time horizon (months)", 0),
    ]
    assert [(item.label, item.value) for item in app.selectbox] == [("Goal", None)]


def test_coach_starter_creates_conversation_and_new_chat_clears_it() -> None:
    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = CoachClient()
    app.session_state["active_user_id"] = "coach-user"
    app.run(timeout=30)

    assert not app.exception
    assert app.chat_input[0].placeholder == "Message your financial coach"
    assert app.button(key="coach-new-chat").disabled is True

    app.button(key="coach-starter-0").click().run(timeout=30)

    assert app.session_state["backend_client"].questions == ["Review my monthly spending"]
    assert app.session_state["coach_history"] == [
        {"role": "user", "content": "Review my monthly spending"},
        {
            "role": "assistant",
            "content": "Start by comparing essential spending with monthly income.",
        },
    ]
    assert app.button(key="coach-new-chat").disabled is False

    app.button(key="coach-new-chat").click().run(timeout=30)
    assert app.session_state["coach_history"] == []
