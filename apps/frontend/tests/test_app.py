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


class SparseProfileClient:
    def __init__(self) -> None:
        self.saved_profile: dict | None = None

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


def test_multipage_app_renders_without_runtime_errors() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = FakeBackendClient()
    app.run(timeout=30)

    assert not app.exception
    assert app.sidebar.selectbox[0].label == "Active profile"
    assert app.sidebar.selectbox[0].options == ["Alex Lee · alex", "Sam Tan · sam"]
    assert app.sidebar.selectbox[1].label == "Period"
    assert app.session_state["active_user_id"] == "alex"


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
