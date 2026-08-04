import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.clients.ai_service import AIServiceUnavailableError
from app.core.config import Settings, settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app


class StubAIServiceClient:
    async def coach(self, request: CoachRequest) -> CoachResponse:
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["budget"],
            answer="Test guidance",
            agent_results=[],
            disclaimers=[],
            audit={"source": "stub"},
        )


class UnavailableAIServiceClient:
    async def coach(self, request: CoachRequest) -> CoachResponse:
        raise AIServiceUnavailableError


client = TestClient(app)


def test_health_is_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Correlation-ID"]


def test_coach_requires_api_key() -> None:
    response = client.post(
        "/api/coach",
        json={"user_id": "u1", "session_id": "s1", "message": "Create a budget"},
    )
    assert response.status_code == 401


def test_coach_forwards_valid_request() -> None:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    try:
        response = client.post(
            "/api/coach",
            headers={"X-API-Key": settings.api_key},
            json={"user_id": "u1", "session_id": "s1", "message": "Create a budget"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["selected_agents"] == ["budget"]
    assert response.headers["X-Correlation-ID"]


def test_coach_hides_downstream_failure_details() -> None:
    app.dependency_overrides[get_ai_service_client] = UnavailableAIServiceClient
    try:
        response = client.post(
            "/api/coach",
            headers={"X-API-Key": settings.api_key},
            json={"user_id": "u1", "session_id": "s1", "message": "Create a budget"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "The coaching service is temporarily unavailable."}


def test_deployment_rejects_weak_service_keys() -> None:
    with pytest.raises(ValueError, match="BACKEND_API_KEY, AI_SERVICE_API_KEY"):
        Settings(APP_ENV="demo", BACKEND_API_KEY="short", AI_SERVICE_API_KEY="short")
