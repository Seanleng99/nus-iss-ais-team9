import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.clients.ai_service import AIServiceUnavailableError
from app.core.config import Settings, settings
from app.core.data_lifecycle import DATA_LIFECYCLE_POLICY_VERSION
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app


class StubAIServiceClient:
    last_request: CoachRequest | None = None

    async def coach(self, request: CoachRequest) -> CoachResponse:
        StubAIServiceClient.last_request = request
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["budget"],
            answer="Test guidance",
            agent_results=[
                {
                    "agent": "budget",
                    "summary": "Test budget summary",
                    "rationale": ["The saved income was used."],
                    "confidence": 0.76,
                },
                {
                    "agent": "risk_compliance",
                    "summary": "Test safety review",
                    "rationale": ["The response remains educational."],
                    "confidence": 0.91,
                },
            ],
            disclaimers=["Educational guidance only."],
            sources=[
                {
                    "source_id": "cpf-beginners-guide-to-investing",
                    "title": "A beginner's guide to investing in Singapore",
                    "issuing_organization": "CPF Board",
                    "canonical_url": "https://www.cpf.gov.sg/example",
                    "published_at": "2026-05-07",
                }
            ],
            audit={
                "trace_id": f"trace-{request.session_id}",
                "source": "stub",
                "model_provider": "local_fixture",
                "model_id": "fixture",
                "prompt_set_version": "v3",
                "dependency_resolutions": [],
                "events": [],
            },
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
        profile_response = client.put(
            "/api/users/u1/profile",
            headers={"X-API-Key": settings.api_key},
            json={"monthly_income": {"currency": "SGD", "amount": 5000}},
        )
        assert profile_response.status_code == 200
        response = client.post(
            "/api/coach",
            headers={"X-API-Key": settings.api_key},
            json={
                "user_id": "u1",
                "session_id": "s1",
                "message": "Create a budget",
                "snapshot": {"monthly_income": {"currency": "SGD", "amount": 1}},
            },
        )
        conversation = client.get(
            "/api/users/u1/chat-sessions/s1",
            headers={"X-API-Key": settings.api_key},
        )
        trace = client.get(
            "/api/coach/traces/trace-s1?user_id=u1",
            headers={"X-API-Key": settings.api_key},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["selected_agents"] == ["budget"]
    assert response.json()["sources"][0]["source_id"] == (
        "cpf-beginners-guide-to-investing"
    )
    assert response.headers["X-Correlation-ID"]
    assert StubAIServiceClient.last_request is not None
    assert StubAIServiceClient.last_request.snapshot.monthly_income is not None
    assert StubAIServiceClient.last_request.snapshot.monthly_income.amount == 5000
    assert [message["role"] for message in conversation.json()["messages"]] == [
        "user",
        "assistant",
    ]
    assert conversation.json()["messages"][1]["content"] == "Test guidance"
    assert conversation.json()["messages"][1]["sources"][0]["source_id"] == (
        "cpf-beginners-guide-to-investing"
    )
    explanation = conversation.json()["messages"][1]["explanation"]
    assert explanation["trace_id"] == "trace-s1"
    assert explanation["selected_agents"] == ["budget"]
    assert explanation["agent_results"][0] == {
        "agent": "budget",
        "rationale": ["The saved income was used."],
        "confidence": 0.76,
        "blocked": False,
    }
    assert explanation["prompt_set_version"] == "v3"
    assert trace.status_code == 200
    assert trace.json()["trace_id"] == "trace-s1"
    assert trace.json()["session_id"] == "s1"
    assert trace.json()["prompt_set_version"] == "v3"
    assert trace.json()["selected_agents"] == ["budget"]


def test_bare_chat_user_does_not_replace_later_request_snapshot() -> None:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    try:
        first = client.post(
            "/api/coach",
            headers={"X-API-Key": settings.api_key},
            json={
                "user_id": "snapshot-user",
                "session_id": "first-chat",
                "message": "Create a budget",
                "snapshot": {"monthly_income": {"currency": "SGD", "amount": 4000}},
            },
        )
        second = client.post(
            "/api/coach",
            headers={"X-API-Key": settings.api_key},
            json={
                "user_id": "snapshot-user",
                "session_id": "second-chat",
                "message": "Assess my emergency fund goal",
                "snapshot": {
                    "monthly_income": {"currency": "SGD", "amount": 5000},
                    "goals": [
                        {
                            "name": "Emergency fund",
                            "target_amount": {"currency": "SGD", "amount": 12000},
                            "target_months": 12,
                        }
                    ],
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert second.status_code == 200
    assert StubAIServiceClient.last_request is not None
    snapshot = StubAIServiceClient.last_request.snapshot
    assert snapshot.monthly_income is not None
    assert snapshot.monthly_income.amount == 5000
    assert [goal.name for goal in snapshot.goals] == ["Emergency fund"]


def test_deleting_only_chat_prunes_chat_only_user() -> None:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    headers = {"X-API-Key": settings.api_key}
    try:
        coached = client.post(
            "/api/coach",
            headers=headers,
            json={
                "user_id": "synthetic-cleanup-user",
                "session_id": "synthetic-cleanup-chat",
                "message": "Create a budget",
                "snapshot": {"monthly_income": {"currency": "SGD", "amount": 4000}},
            },
        )
        deleted = client.delete(
            "/api/users/synthetic-cleanup-user/chat-sessions/synthetic-cleanup-chat",
            headers=headers,
        )
        recreate = client.post(
            "/api/users/synthetic-cleanup-user/chat-sessions",
            headers=headers,
            json={"id": "should-not-exist", "title": "Orphan check"},
        )
    finally:
        app.dependency_overrides.clear()

    assert coached.status_code == 200
    assert deleted.status_code == 204
    assert recreate.status_code == 404


def test_trace_is_isolated_to_its_profile() -> None:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    try:
        response = client.post(
            "/api/coach",
            headers={"X-API-Key": settings.api_key},
            json={"user_id": "owner", "session_id": "owned", "message": "Budget"},
        )
        trace = client.get(
            "/api/coach/traces/trace-owned?user_id=other-user",
            headers={"X-API-Key": settings.api_key},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert trace.status_code == 404


def test_trace_can_only_be_deleted_by_its_profile() -> None:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    try:
        response = client.post(
            "/api/coach",
            headers={"X-API-Key": settings.api_key},
            json={"user_id": "owner", "session_id": "deletable", "message": "Budget"},
        )
        wrong_owner = client.delete(
            "/api/coach/traces/trace-deletable?user_id=other-user",
            headers={"X-API-Key": settings.api_key},
        )
        deleted = client.delete(
            "/api/coach/traces/trace-deletable?user_id=owner",
            headers={"X-API-Key": settings.api_key},
        )
        missing = client.get(
            "/api/coach/traces/trace-deletable?user_id=owner",
            headers={"X-API-Key": settings.api_key},
        )
        conversation = client.get(
            "/api/users/owner/chat-sessions/deletable",
            headers={"X-API-Key": settings.api_key},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert wrong_owner.status_code == 404
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert conversation.status_code == 200
    assert conversation.json()["messages"][1]["content"] == "Test guidance"
    assert conversation.json()["messages"][1]["explanation"] is None


def test_complete_workspace_deletion_cascades_to_messages_and_traces() -> None:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    headers = {"X-API-Key": settings.api_key}
    try:
        assert client.put(
            "/api/users/cascade-user/profile", headers=headers, json={}
        ).status_code == 200
        coached = client.post(
            "/api/coach",
            headers=headers,
            json={
                "user_id": "cascade-user",
                "session_id": "cascade-chat",
                "message": "Create a budget",
            },
        )
        exported = client.get(
            "/api/users/cascade-user/data-export", headers=headers
        )
        deleted = client.request(
            "DELETE",
            "/api/users/cascade-user/data",
            headers=headers,
            json={
                "confirm_user_id": "cascade-user",
                "policy_version": DATA_LIFECYCLE_POLICY_VERSION,
            },
        )
        missing_trace = client.get(
            "/api/coach/traces/trace-cascade-chat?user_id=cascade-user",
            headers=headers,
        )
    finally:
        app.dependency_overrides.clear()

    assert coached.status_code == 200
    exported_trace = exported.json()["data"]["chat_sessions"][0]["messages"][1][
        "orchestration_trace"
    ]
    assert exported_trace["trace_id"] == "trace-cascade-chat"
    assert deleted.status_code == 200
    assert deleted.json()["deleted_counts"]["chat_messages"] == 2
    assert deleted.json()["deleted_counts"]["orchestration_traces"] == 1
    assert missing_trace.status_code == 404


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


def test_runtime_cannot_extend_retention_or_enable_policy_disabled_memory() -> None:
    with pytest.raises(ValueError, match="TRACE_RETENTION_DAYS"):
        Settings(TRACE_RETENTION_DAYS=31)
    with pytest.raises(ValueError, match="DURABLE_AGENT_MEMORY_ENABLED"):
        Settings(DURABLE_AGENT_MEMORY_ENABLED=True)


def test_deployment_requires_https_oidc_configuration_when_enabled() -> None:
    secure_key = "a-secure-service-key-that-is-long-enough"
    with pytest.raises(ValueError, match="OIDC_ISSUER_URL, OIDC_JWKS_URL, OIDC_CLIENT_ID"):
        Settings(
            APP_ENV="demo",
            BACKEND_API_KEY=secure_key,
            AI_SERVICE_API_KEY=secure_key,
            POSTGRES_SSLMODE="require",
            OIDC_AUTH_ENABLED=True,
        )
    with pytest.raises(ValueError, match="OIDC_ISSUER_URL, OIDC_JWKS_URL must use HTTPS"):
        Settings(
            APP_ENV="demo",
            BACKEND_API_KEY=secure_key,
            AI_SERVICE_API_KEY=secure_key,
            POSTGRES_SSLMODE="require",
            OIDC_AUTH_ENABLED=True,
            OIDC_ISSUER_URL="http://issuer.example",
            OIDC_JWKS_URL="http://issuer.example/jwks.json",
            OIDC_CLIENT_ID="coach-client",
        )
    with pytest.raises(ValueError, match="OIDC_REQUIRED_TOKEN_USE must be id"):
        Settings(
            APP_ENV="demo",
            BACKEND_API_KEY=secure_key,
            AI_SERVICE_API_KEY=secure_key,
            POSTGRES_SSLMODE="require",
            OIDC_AUTH_ENABLED=True,
            OIDC_ISSUER_URL="https://issuer.example",
            OIDC_JWKS_URL="https://issuer.example/jwks.json",
            OIDC_CLIENT_ID="coach-client",
        )
