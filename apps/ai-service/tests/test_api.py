import json
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import app, get_orchestrator
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.retriever import RetrievalError

test_config = Settings(MODEL_PROVIDER="local_fixture")
test_orchestrator = AgentOrchestrator(
    config=test_config,
    gateway=LocalFixtureModelGateway(),
)
app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator
client = TestClient(app)


def test_health_is_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Correlation-ID"]


def test_coach_requires_api_key() -> None:
    response = client.post(
        "/coach",
        json={"user_id": "u1", "session_id": "s1", "message": "Create a budget"},
    )
    assert response.status_code == 401


def test_coach_accepts_valid_api_key() -> None:
    response = client.post(
        "/coach",
        headers={"X-API-Key": settings.api_key},
        json={"user_id": "u1", "session_id": "s1", "message": "Create a budget"},
    )
    assert response.status_code == 200
    assert response.json()["selected_agents"] == ["budget"]
    assert response.json()["audit"]["executed_at"]


def test_correlation_id_is_preserved_but_does_not_control_trace_identity() -> None:
    response = client.post(
        "/coach",
        headers={"X-API-Key": settings.api_key, "X-Correlation-ID": "test-trace"},
        json={"user_id": "u1", "session_id": "s1", "message": "Create a budget"},
    )
    assert response.headers["X-Correlation-ID"] == "test-trace"
    assert UUID(response.json()["audit"]["trace_id"])
    assert response.json()["audit"]["trace_id"] != "test-trace"


@pytest.mark.parametrize("supplied", ["x" * 129, "bad correlation id"])
def test_invalid_correlation_ids_are_replaced(supplied) -> None:
    response = client.get("/health", headers={"X-Correlation-ID": supplied})
    assert response.status_code == 200
    assert UUID(response.headers["X-Correlation-ID"])


def test_deployment_rejects_weak_api_key() -> None:
    with pytest.raises(ValueError, match="AI_SERVICE_API_KEY"):
        Settings(APP_ENV="demo", AI_SERVICE_API_KEY="short")


def test_deployment_rejects_fixture_model() -> None:
    with pytest.raises(ValueError, match="MODEL_PROVIDER=bedrock"):
        Settings(
            APP_ENV="demo",
            AI_SERVICE_API_KEY="a-secure-demo-key-that-is-long-enough",
            MODEL_PROVIDER="local_fixture",
        )


def test_coach_returns_and_logs_sanitized_model_failure(caplog) -> None:
    class FailingGateway:
        def generate(self, **kwargs) -> str:
            raise ModelGatewayError("provider detail that must not escape")

    failed = AgentOrchestrator(config=test_config, gateway=FailingGateway())
    app.dependency_overrides[get_orchestrator] = lambda: failed
    with caplog.at_level(logging.ERROR, logger="service.ai"):
        response = client.post(
            "/coach",
            headers={
                "X-API-Key": settings.api_key,
                "X-Correlation-ID": "failure-trace",
            },
            json={
                "user_id": "u1",
                "session_id": "s1",
                "message": "Create a budget",
            },
        )
    app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator
    assert response.status_code == 503
    assert "provider detail" not in response.text
    failure = next(
        json.loads(record.message)
        for record in caplog.records
        if '"event":"coach_generation_failed"' in record.message
    )
    assert failure == {
        "event": "coach_generation_failed",
        "correlation_id": "failure-trace",
        "error_code": "MODEL_GATEWAY_ERROR",
        "component": "orchestrator",
        "exception_type": "ModelGatewayError",
    }
    assert "provider detail" not in caplog.text


def test_coach_returns_sanitized_retrieval_failure() -> None:
    class FailingEducationRetriever:
        def retrieve(self, query: str, top_k: int = 3) -> list:
            del query, top_k
            raise RetrievalError("sensitive knowledge base detail")

    failed = AgentOrchestrator(
        config=test_config,
        gateway=LocalFixtureModelGateway(),
        education_retriever=FailingEducationRetriever(),
    )
    app.dependency_overrides[get_orchestrator] = lambda: failed
    response = client.post(
        "/coach",
        headers={"X-API-Key": settings.api_key},
        json={
            "user_id": "u1",
            "session_id": "s1",
            "message": "Explain ETF diversification",
        },
    )
    app.dependency_overrides[get_orchestrator] = lambda: test_orchestrator

    assert response.status_code == 503
    assert "sensitive knowledge base detail" not in response.text
