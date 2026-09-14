import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes import _finalize_coach_response
from app.core import observability, security, telemetry
from app.core.config import Settings, settings
from app.core.observability import RequestTelemetryMiddleware
from app.core.security import AuthenticatedPrincipal, OidcTokenVerifier
from app.domain.schemas import CoachResponse
from app.infrastructure.database import get_db_session
from app.infrastructure.models import (
    ChatMessageRecord,
    ChatSessionRecord,
    OrchestrationTraceRecord,
    UserRecord,
)
from app.main import app

HEADERS = {
    "X-Correlation-ID": "frontend-operation-001",
    "X-Journey-ID": "a" * 32,
    "X-Parent-Span-ID": "b" * 16,
    "X-Caller-Method": "client.BackendClient.coach",
}
PAYLOAD = {
    "user_id": "private-profile-marker",
    "session_id": "private-session-marker",
    "message": "Private question marker: income is 987654.32",
    "snapshot": {"monthly_income": {"amount": 987654.32}},
}


def _ai_payload():
    return {
        "session_id": PAYLOAD["session_id"],
        "selected_agents": ["budget"],
        "answer": "Private answer marker",
        "agent_results": [{
            "agent": "budget",
            "summary": "Private model summary marker",
            "rationale": ["Private generated explanation marker"],
        }],
        "disclaimers": ["Private disclaimer marker"],
        "sources": [{
            "source_id": "private-source-marker",
            "title": "Private source title marker",
            "issuing_organization": "Private source organization marker",
            "canonical_url": "https://private.example/source?secret=source-marker",
            "published_at": "2026-01-01",
        }],
        "audit": {"trace_id": "trace-safe-001", "private": "Private audit marker"},
    }


@pytest.fixture
def service_logs(caplog):
    caplog.set_level(logging.INFO, logger="service")
    return caplog


def _events(caplog, correlation_id=None):
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name.startswith("service.")
    ]
    if correlation_id is not None:
        events = [event for event in events if event["correlation_id"] == correlation_id]
    return events


@pytest.fixture
def ai_response():
    return _ai_payload()


@pytest.fixture
def mocked_ai(monkeypatch, ai_response):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=ai_response)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: AsyncClient(transport=transport, **kwargs)
    )
    return requests


def _assert_content_free(caplog):
    sensitive = [
        settings.api_key, settings.ai_service_api_key,
        PAYLOAD["user_id"], PAYLOAD["session_id"], PAYLOAD["message"], "987654.32",
        "Private answer marker", "Private model summary marker",
        "Private generated explanation marker", "Private disclaimer marker",
        "private-source-marker", "Private source title marker",
        "Private source organization marker", "private.example", "Private audit marker",
        "private-error-marker", "private-bearer-marker", "private-owner-marker",
    ]
    for value in sensitive:
        assert value not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_frontend_headers_link_auth_snapshot_ai_persistence_and_response(
    mocked_ai, service_logs,
):
    client = TestClient(app)
    assert client.put(
        f"/api/users/{PAYLOAD['user_id']}/profile",
        headers={"X-API-Key": settings.api_key},
        json={"monthly_income": PAYLOAD["snapshot"]["monthly_income"]},
    ).status_code == 200
    service_logs.clear()

    response = client.post(
        "/api/coach", headers={**HEADERS, "X-API-Key": settings.api_key}, json=PAYLOAD
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == HEADERS["X-Correlation-ID"]
    assert response.json()["answer"] == _ai_payload()["answer"]
    assert len(mocked_ai) == 1
    sent_headers = mocked_ai[0].headers
    assert sent_headers["X-Correlation-ID"] == HEADERS["X-Correlation-ID"]
    assert sent_headers["X-Journey-ID"] == HEADERS["X-Journey-ID"]
    assert sent_headers["X-API-Key"] == settings.ai_service_api_key
    assert sent_headers["X-Caller-Method"] == "app.clients.ai_service.AIServiceClient.coach"
    events = _events(service_logs)
    assert {event["correlation_id"] for event in events} == {HEADERS["X-Correlation-ID"]}
    assert {event["journey_id"] for event in events} == {HEADERS["X-Journey-ID"]}
    started = {event["span_id"]: event for event in events if event["event"] == "method.started"}
    methods = {event["method"] for event in started.values()}
    expected_methods = {
        "app.core.observability.RequestTelemetryMiddleware.dispatch",
        "app.core.security.require_principal",
        "app.core.security.enforce_user_access",
        "app.core.security.enforce_automation_user_scope",
        "app.api.routes.coach",
        "app.clients.ai_service.AIServiceClient.coach",
        "pydantic.main.BaseModel.model_validate",
        "app.domain.schemas.CoachResponse.sanitize_blocked_response",
        "sqlalchemy.orm.session.Session.commit",
        "app.api.routes._finalize_coach_response",
    }
    expected_methods.update(
        f"app.infrastructure.repositories.{method}" for method in (
            "SQLAlchemyUserRepository.get_financial_snapshot",
            "SQLAlchemyUserRepository.get_profile",
            "SQLAlchemyTransactionRepository.list_for_user",
            "SQLAlchemyGoalRepository.list_for_user",
            "SQLAlchemyChatRepository.get_for_update",
            "SQLAlchemyChatRepository.id_exists",
            "SQLAlchemyChatRepository.create",
            "SQLAlchemyChatRepository.append_message",
            "SQLAlchemyOrchestrationTraceRepository.create",
        )
    )
    assert expected_methods <= methods
    ai_span = started[sent_headers["X-Parent-Span-ID"]]
    assert ai_span["method"] == sent_headers["X-Caller-Method"]
    assert ai_span["caller_method"] == "app.api.routes.coach"
    for span_id, event in started.items():
        if event["method"].endswith("RequestTelemetryMiddleware.dispatch"):
            assert event["parent_span_id"] == HEADERS["X-Parent-Span-ID"]
            assert event["caller_method"] == HEADERS["X-Caller-Method"]
        else:
            assert event["caller_method"] == started[event["parent_span_id"]]["method"]
        completed = [
            item for item in events
            if item.get("span_id") == span_id and item["event"] == "method.completed"
        ]
        assert len(completed) == 1
        assert completed[0]["duration_ms"] >= 0
    ready = next(event for event in events if event["event"] == "coach.response.ready")
    assert ready["selected_agents"] == ["budget"]
    assert ready["blocked"] is False
    assert ready["source_count"] == 1
    assert ready["response_fields"] == list(CoachResponse.model_fields)
    assert ready["output_characters"] == len(_ai_payload()["answer"])
    assert ready["trace_id"] == "trace-safe-001"
    assert any(event["event"] == "coach.persistence.completed" for event in events)
    assert any(event["event"] == "auth.accepted" for event in events)
    assert any(event["event"] == "ai_service.response.validated" for event in events)
    assert observability._correlation_id is telemetry._correlation_id
    assert observability.get_correlation_id() is None
    assert telemetry.context_fields() == {"correlation_id": None, "journey_id": None}
    _assert_content_free(service_logs)


def test_history_reload_traces_saved_answer_and_explanation_packaging(mocked_ai, service_logs):
    client = TestClient(app)
    headers = {**HEADERS, "X-API-Key": settings.api_key}
    assert client.post("/api/coach", headers=headers, json=PAYLOAD).status_code == 200
    service_logs.clear()
    response = client.get(
        f"/api/users/{PAYLOAD['user_id']}/chat-sessions/{PAYLOAD['session_id']}",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["messages"][-1]["content"] == _ai_payload()["answer"]
    methods = {
        event.get("method") for event in _events(service_logs)
        if event["event"] == "method.started"
    }
    assert {
        "app.api.financial.get_chat_session",
        "app.infrastructure.repositories.SQLAlchemyChatRepository.get",
        "app.api.financial._chat_session_response",
        "app.api.financial._message_explanation",
        "app.api.financial_schemas.ChatMessageResponse.sanitize_blocked_assistant_message",
        "app.api.financial_schemas.ChatExplanationResponse.sanitize_blocked_explanation",
    } <= methods
    _assert_content_free(service_logs)


@pytest.mark.parametrize("authorization", [None, "Basic private-bearer-marker", "Bearer private-bearer-marker"])
def test_denied_auth_returns_correlation_without_forwarding(
    authorization, mocked_ai, service_logs, monkeypatch,
):
    monkeypatch.setattr(settings, "oidc_auth_enabled", True)

    def reject(_token):
        raise ValueError("private-error-marker")

    monkeypatch.setattr(
        security, "get_oidc_token_verifier", lambda: SimpleNamespace(verify=reject)
    )
    headers = {**HEADERS, "X-Synthetic-Log": "true"}
    if authorization:
        headers.update({"Authorization": authorization, "X-API-Key": settings.api_key})
    response = TestClient(app).post(
        "/api/coach", headers=headers,
        json={**PAYLOAD, "user_id": "deployment-synthetic-log-test"},
    )

    assert response.status_code == 401
    assert response.headers["X-Correlation-ID"] == HEADERS["X-Correlation-ID"]
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert mocked_ai == []
    events = _events(service_logs)
    assert any(event["event"] == "auth.denied" for event in events)
    assert not any(event.get("synthetic_content") for event in events)
    assert any(
        event["event"] == "method.failed"
        and event["method"] == "app.core.security.require_principal"
        and event["exception_type"] == "HTTPException"
        for event in events
    )
    assert next(event for event in events if event["event"] == "request")["status_code"] == 401
    _assert_content_free(service_logs)


def test_oidc_verification_logs_success_and_failure_without_claims(service_logs):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = OidcTokenVerifier(Settings(
        OIDC_ISSUER_URL="https://private.example",
        OIDC_JWKS_URL="https://private.example/jwks",
        OIDC_CLIENT_ID="private-client-marker",
        OIDC_REQUIRED_TOKEN_USE="id",
    ))
    verifier._jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())
    )
    now = datetime.now(UTC)
    claims = {
        "iss": "https://private.example", "aud": "private-client-marker",
        "sub": "private-owner-marker", "iat": now,
        "exp": now + timedelta(minutes=5), "token_use": "id",
    }
    token = jwt.encode(claims, key, algorithm="RS256")
    invalid_token = jwt.encode({**claims, "aud": "other-client"}, key, algorithm="RS256")
    with telemetry.trace_context(correlation_id="oidc-operation"):
        assert verifier.verify(token).subject == "private-owner-marker"
        with pytest.raises(jwt.InvalidAudienceError):
            verifier.verify(invalid_token)
    events = _events(service_logs)
    assert {"auth.oidc.accepted", "auth.oidc.denied"} <= {event["event"] for event in events}
    assert [
        event["event"] for event in events
        if event["event"] in {"method.completed", "method.failed"}
    ] == ["method.completed", "method.failed"]
    assert token not in service_logs.text
    assert invalid_token not in service_logs.text
    assert "private-client-marker" not in service_logs.text
    _assert_content_free(service_logs)


@pytest.mark.parametrize("failure_at", ["messages", "trace", "commit"])
@pytest.mark.parametrize("marked", [False, True])
def test_persistence_failure_logs_type_and_rolls_back(
    failure_at, marked, mocked_ai, service_logs, monkeypatch,
):
    original_flush = Session.flush

    def fail_flush(session, *args, **kwargs):
        target = ChatMessageRecord if failure_at == "messages" else OrchestrationTraceRecord
        if any(isinstance(record, target) for record in session.new):
            raise IntegrityError("private-error-marker", {"owner": PAYLOAD["user_id"]}, None)
        return original_flush(session, *args, **kwargs)

    def fail_commit(session):
        raise IntegrityError("private-error-marker", {"owner": PAYLOAD["user_id"]}, None)

    monkeypatch.setattr(Session, "commit" if failure_at == "commit" else "flush",
                        fail_commit if failure_at == "commit" else fail_flush)
    headers = {**HEADERS, "X-API-Key": settings.api_key}
    if marked:
        headers["X-Synthetic-Log"] = "true"
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/coach", headers=headers,
        json={**PAYLOAD, "user_id": "deployment-synthetic-log-test"},
    )
    assert response.status_code == 500
    events = _events(service_logs)
    failed_methods = {
        event["method"] for event in events
        if event["event"] == "method.failed" and event["exception_type"] == "IntegrityError"
    }
    expected_method = {
        "messages": "app.infrastructure.repositories.SQLAlchemyChatRepository.append_message",
        "trace": "app.infrastructure.repositories.SQLAlchemyOrchestrationTraceRepository.create",
        "commit": "sqlalchemy.orm.session.Session.commit",
    }[failure_at]
    assert expected_method in failed_methods
    assert "app.api.routes.coach" in failed_methods
    assert any(event["event"] == "request_failed" for event in events)
    assert not any(event["event"] == "coach.response.ready" for event in events)
    assert not any(event["event"] == "coach.persistence.completed" for event in events)
    assert not any(event.get("synthetic_content") for event in events)
    dependency = app.dependency_overrides[get_db_session]()
    try:
        session = next(dependency)
        for model in (ChatSessionRecord, ChatMessageRecord, OrchestrationTraceRecord):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    finally:
        dependency.close()
    _assert_content_free(service_logs)


@pytest.mark.parametrize("failure", ["http_status", "transport", "schema", "json"])
@pytest.mark.parametrize("marked", [False, True])
def test_ai_failures_log_status_and_type_without_raw_response(
    failure, marked, service_logs, monkeypatch,
):
    def respond(request):
        if failure == "transport":
            raise httpx.ReadTimeout("private-error-marker", request=request)
        if failure == "http_status":
            return httpx.Response(502, text="private-error-marker")
        if failure == "json":
            return httpx.Response(200, text="private-error-marker")
        return httpx.Response(200, json={"session_id": "private-error-marker"})

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: AsyncClient(transport=httpx.MockTransport(respond), **kwargs),
    )
    headers = {**HEADERS, "X-API-Key": settings.api_key}
    if marked:
        headers["X-Synthetic-Log"] = "true"
    response = TestClient(app).post(
        "/api/coach", headers=headers,
        json={**PAYLOAD, "user_id": "deployment-synthetic-log-test"},
    )
    assert response.status_code == 503
    assert response.headers["X-Correlation-ID"] == HEADERS["X-Correlation-ID"]
    events = _events(service_logs)
    failure_event = next(event for event in events if event["event"] == "ai_service.failed")
    assert failure_event["exception_type"] == {
        "http_status": "HTTPStatusError", "transport": "ReadTimeout",
        "schema": "ValidationError", "json": "JSONDecodeError",
    }[failure]
    if failure == "http_status":
        assert failure_event["status_code"] == 502
    assert not any(event["event"] == "coach.response.ready" for event in events)
    assert not any(event.get("synthetic_content") for event in events)
    _assert_content_free(service_logs)


def test_access_logs_templates_and_unmatched_paths(service_logs):
    client = TestClient(app)
    headers = {**HEADERS, "X-API-Key": settings.api_key}
    assert client.get(
        f"/api/users/{PAYLOAD['user_id']}/profile?question=private-query-marker", headers=headers
    ).status_code == 404
    assert client.get("/private-path-marker?secret=private-query-marker", headers=headers).status_code == 404
    access = [event for event in _events(service_logs) if event["event"] == "request"]
    assert [event["route"] for event in access] == ["/users/{user_id}/profile", "<unmatched>"]
    assert all(event["http_method"] == "GET" and event["duration_ms"] >= 0 for event in access)
    assert "private-query-marker" not in service_logs.text
    assert "private-path-marker" not in service_logs.text
    _assert_content_free(service_logs)


def test_health_success_is_quiet_but_failures_are_logged(service_logs):
    response = TestClient(app).get("/health", headers=HEADERS)
    assert response.headers["X-Correlation-ID"] == HEADERS["X-Correlation-ID"]
    assert _events(service_logs) == []
    broken_app = FastAPI()
    broken_app.add_middleware(RequestTelemetryMiddleware, service_name="backend")

    @broken_app.get("/health")
    def broken_health():
        raise HTTPException(status_code=503, detail="private-error-marker")

    failed = TestClient(broken_app).get("/health", headers=HEADERS)
    assert failed.status_code == 503
    assert failed.headers["X-Correlation-ID"] == HEADERS["X-Correlation-ID"]
    assert any(event["status_code"] == 503 for event in _events(service_logs))
    _assert_content_free(service_logs)


@pytest.mark.parametrize("trace_id", ["https://private.example", "private person name", ["private-person"]])
def test_ready_event_rejects_non_identifier_trace_ids(trace_id, service_logs):
    payload = _ai_payload()
    payload["audit"]["trace_id"] = trace_id
    response = CoachResponse.model_validate(payload)
    assert _finalize_coach_response(response) is response
    ready = next(event for event in _events(service_logs) if event["event"] == "coach.response.ready")
    assert "trace_id" not in ready
    _assert_content_free(service_logs)


def test_concurrent_requests_keep_context_isolated(service_logs):
    async def run_requests():
        test_app = FastAPI()
        test_app.add_middleware(RequestTelemetryMiddleware, service_name="backend")
        both_arrived = asyncio.Event()
        arrivals = 0

        @test_app.get("/probe")
        async def probe():
            nonlocal arrivals
            arrivals += 1
            if arrivals == 2:
                both_arrived.set()
            await asyncio.wait_for(both_arrived.wait(), timeout=2)
            return telemetry.outbound_headers()

        with telemetry.trace_context(correlation_id="outer-operation", journey_id="c" * 32):
            outer_context = telemetry.context_fields()
            async with AsyncClient(
                transport=httpx.ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                responses = await asyncio.gather(*(
                    client.get("/probe", headers={
                        **HEADERS, "X-Correlation-ID": f"operation-{index}",
                        "X-Journey-ID": str(index) * 32,
                    }) for index in (1, 2)
                ))
                for index, response in enumerate(responses, start=1):
                    assert response.headers["X-Correlation-ID"] == f"operation-{index}"
                    assert response.json()["X-Correlation-ID"] == f"operation-{index}"
                    assert response.json()["X-Journey-ID"] == str(index) * 32
                assert telemetry.context_fields() == outer_context
        assert telemetry.context_fields() == {"correlation_id": None, "journey_id": None}

    asyncio.run(run_requests())
    for index in (1, 2):
        events = _events(service_logs, f"operation-{index}")
        assert events
        assert {event["journey_id"] for event in events} == {str(index) * 32}


@pytest.mark.parametrize("environment", ["local", "test", "demo"])
@pytest.mark.parametrize("blocked", [False, True])
def test_marked_reserved_automation_logs_only_complete_question_and_final_safe_answer(
    environment, blocked, mocked_ai, ai_response, service_logs, monkeypatch,
):
    monkeypatch.setattr(settings, "app_env", environment)
    ai_response["blocked"] = blocked
    ai_response["answer"] = "Synthetic final answer. " * 250
    payload = {
        **PAYLOAD, "user_id": "deployment-synthetic-log-test",
        "message": "Synthetic question. " * 200,
    }
    response = TestClient(app).post(
        "/api/coach",
        headers={**HEADERS, "X-API-Key": settings.api_key, "X-Synthetic-Log": "true"},
        json=payload,
    )
    assert response.status_code == 200
    assert "X-Synthetic-Log" not in mocked_ai[0].headers
    assert "synthetic" not in json.loads(mocked_ai[0].content)
    events = _events(service_logs)
    exchanges = [event for event in events if event.get("synthetic_content")]
    assert len(exchanges) == 1
    exchange = exchanges[0]
    assert exchange["event"] == "coach.synthetic.exchange"
    assert exchange["question"] == payload["message"].strip()
    assert exchange["answer"] == response.json()["answer"]
    assert exchange["correlation_id"] == HEADERS["X-Correlation-ID"]
    assert exchange["journey_id"] == HEADERS["X-Journey-ID"]
    assert exchange["method"] == "app.api.routes.coach"
    assert exchange["parent_span_id"]
    commit_index = next(
        index for index, event in enumerate(events)
        if event["event"] == "method.completed"
        and event["method"] == "sqlalchemy.orm.session.Session.commit"
    )
    assert commit_index < events.index(exchange)
    assert "audit" not in exchange
    assert "agent_results" not in exchange
    assert "Private generated explanation marker" not in service_logs.text
    assert "Private model summary marker" not in service_logs.text
    assert "Private audit marker" not in service_logs.text
    other_events = json.dumps([event for event in events if event is not exchange])
    assert payload["message"].strip() not in other_events
    assert ai_response["answer"] not in other_events
    if blocked:
        assert ai_response["answer"] not in service_logs.text


@pytest.mark.parametrize(("user_id", "marker", "environment"), [
    ("deployment-synthetic-log-test", None, "local"),
    ("deployment-synthetic-log-test", "false", "local"),
    ("deployment-synthetic-log-test", "True", "local"),
    ("deployment-synthetic-log-test", " true", "local"),
    ("deployment-synthetic-log-test", "true ", "local"),
    ("private-profile-marker", "true", "local"),
    ("deployment-synthetic-log-test", "true", "production"),
])
def test_synthetic_logging_requires_exact_marker_reserved_profile_and_demo_environment(
    user_id, marker, environment, mocked_ai, service_logs, monkeypatch,
):
    monkeypatch.setattr(settings, "app_env", environment)
    headers = {**HEADERS, "X-API-Key": settings.api_key}
    if marker is not None:
        headers["X-Synthetic-Log"] = marker
    response = TestClient(app).post(
        "/api/coach", headers=headers, json={**PAYLOAD, "user_id": user_id}
    )
    assert response.status_code == 200
    assert not any(event.get("synthetic_content") for event in _events(service_logs))
    _assert_content_free(service_logs)


def test_oidc_owner_cannot_enable_synthetic_logging_with_reserved_prefix(
    mocked_ai, service_logs, monkeypatch,
):
    user_id = "deployment-synthetic-log-test"
    principal = AuthenticatedPrincipal(
        authentication_method="oidc", issuer="https://private.example",
        subject="private-owner-marker",
    )
    monkeypatch.setattr(settings, "oidc_auth_enabled", True)
    monkeypatch.setattr(
        security, "get_oidc_token_verifier", lambda: SimpleNamespace(verify=lambda token: principal)
    )
    dependency = app.dependency_overrides[get_db_session]()
    try:
        session = next(dependency)
        session.add(UserRecord(
            id=user_id, owner_issuer=principal.issuer, owner_subject=principal.subject
        ))
        session.commit()
    finally:
        dependency.close()
    service_logs.clear()
    response = TestClient(app).post(
        "/api/coach",
        headers={
            **HEADERS, "Authorization": "Bearer private-bearer-marker",
            "X-API-Key": settings.api_key, "X-Synthetic-Log": "true",
        },
        json={**PAYLOAD, "user_id": user_id},
    )
    assert response.status_code == 200
    events = _events(service_logs)
    assert any(
        event["event"] == "auth.accepted" and event["authentication_method"] == "oidc"
        for event in events
    )
    assert not any(event.get("synthetic_content") for event in events)
    _assert_content_free(service_logs)
