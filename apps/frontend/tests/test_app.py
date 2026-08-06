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


def test_multipage_app_renders_without_runtime_errors() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = FakeBackendClient()
    app.run(timeout=30)

    assert not app.exception
    assert app.sidebar.selectbox[0].label == "Active profile"
    assert app.sidebar.selectbox[0].options == ["Alex Lee · alex", "Sam Tan · sam"]
    assert app.sidebar.selectbox[1].label == "Period"
    assert app.session_state["active_user_id"] == "alex"
