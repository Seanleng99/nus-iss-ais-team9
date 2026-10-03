import pytest
from fastapi.testclient import TestClient
from language_fixtures import language_case

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachResponse
from app.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class BlockedAI:
    last_request = None

    async def coach(self, request):
        self.last_request = request
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=[],
            answer="UNREVIEWED_MODEL_TEXT",
            agent_results=[],
            disclaimers=[],
            blocked=True,
            audit={"trace_id": f"locale-{request.session_id}", "response_language": "English"},
        )


@pytest.mark.parametrize(
    "message,selection,expected",
    [
        ("Explain ETF risks.", None, "zh-Hans"),
        ("Explain ETF risks.", "en", "en"),
        (
            language_case(
                "language_selection.test_owned_profile_selection_and_explicit_instruction_reach_ai_and_saved_history"
            ),
            "zh-Hans",
            "zh-Hans",
        ),
    ],
)
def test_owned_profile_selection_and_explicit_instruction_reach_ai_and_saved_history(
    monkeypatch,
    message,
    selection,
    expected,
):
    fake = BlockedAI()
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: fake)
    profile = client.post(
        "/api/profiles",
        headers=HEADERS,
        json={
            "user_id": "locale-profile",
            "preferred_language": "Mandarin",
        },
    )
    assert profile.status_code == 201
    payload = {
        "user_id": "locale-profile",
        "session_id": "locale-profile-session",
        "message": message,
        "snapshot": {"preferences": {"preferred_language": "English"}},
    }
    if selection:
        payload["response_locale"] = selection
    response = client.post("/api/coach", headers=HEADERS, json=payload)
    assert response.status_code == 200
    body = response.json()
    assert fake.last_request.response_locale == expected
    assert body["audit"]["response_locale"] == expected
    assert body["audit"]["response_language"] == ("Chinese" if expected == "zh-Hans" else "English")
    assert "UNREVIEWED" not in str(body)
    saved = client.get(
        "/api/users/locale-profile/chat-sessions/locale-profile-session", headers=HEADERS
    )
    assert saved.status_code == 200
    assert saved.json()["messages"][-1]["content"] == body["answer"]


def test_language_requests_in_history_cannot_change_the_default_language(monkeypatch):
    fake = BlockedAI()
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: fake)
    payload = {"user_id": "locale-history", "session_id": "locale-history-session"}
    for message in ["Explain ETFs in Chinese.", "Give an example."]:
        response = client.post("/api/coach", headers=HEADERS, json={**payload, "message": message})
        assert response.status_code == 200
        assert fake.last_request.response_locale == "en"
        assert response.json()["audit"]["response_language"] == "English"


def test_unsupported_explicit_response_locale_is_rejected_before_ai(monkeypatch):
    fake = BlockedAI()
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: fake)
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={
            "user_id": "locale-unsupported",
            "session_id": "locale-unsupported-session",
            "message": "Explain ETFs.",
            "response_locale": "fr",
        },
    )
    assert response.status_code == 422
    assert fake.last_request is None
