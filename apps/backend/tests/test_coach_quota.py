from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes import get_ai_service_client
from app.clients.ai_service import AIServiceUnavailableError
from app.core.config import Settings, settings
from app.core.run_trace import record_event
from app.core.security import AuthenticatedPrincipal
from app.domain.schemas import CoachResponse
from app.infrastructure.database import Base
from app.infrastructure.models import (
    ChatSessionRecord,
    CoachQuotaLease,
    CoachQuotaRecord,
    OrchestrationTraceRecord,
    UserRecord,
)
from app.main import app
from app.services.coach_quota import (
    CoachQuota,
    known_tokens,
    known_trace_tokens,
    principal_key,
    purge_quota_records,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
PRINCIPAL = AuthenticatedPrincipal("oidc", "https://issuer.example", "synthetic-subject")


@pytest.fixture
def quota(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'quota.db'}")
    Base.metadata.create_all(engine)
    config = Settings(_env_file=None, COACH_REQUESTS_PER_MINUTE=3, COACH_CONCURRENT_REQUESTS=2,
                      MAX_MODEL_TOKENS_PER_RUN=1000, COACH_TOKENS_PER_HOUR=2000)
    yield CoachQuota(engine, config)
    engine.dispose()


def response(tokens=200):
    return CoachResponse(session_id="test", selected_agents=[], agent_results=[], answer="Useful guidance", disclaimers=[],
                         audit={"model_call_count": 1, "model_calls": [{"status": "completed",
                             "input_tokens": tokens - 10, "output_tokens": 10, "total_tokens": tokens}]})


def test_shared_concurrency_is_atomic_across_independent_controllers(quota):
    def acquire(_):
        try:
            return CoachQuota(quota.engine, quota.config).acquire(PRINCIPAL, now=NOW)
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(acquire, range(4)))
    assert results.count(429) == 2
    with Session(quota.engine) as session:
        assert len(session.scalars(select(CoachQuotaLease)).all()) == 2


def test_minute_rate_survives_completion_and_new_controller(quota):
    for _ in range(3):
        lease = quota.acquire(PRINCIPAL, now=NOW)
        quota.finish(lease, response(100))
    with pytest.raises(HTTPException) as denied:
        CoachQuota(quota.engine, quota.config).acquire(PRINCIPAL, now=NOW)
    assert denied.value.status_code == 429
    assert denied.value.headers["Retry-After"] == "60"
    assert quota.acquire(PRINCIPAL, now=NOW + timedelta(minutes=1))


def test_failed_or_unknown_usage_retains_reservation_until_hour_rollover(quota):
    for _ in range(2):
        quota.finish(quota.acquire(PRINCIPAL, now=NOW))
    with pytest.raises(HTTPException) as denied:
        quota.acquire(PRINCIPAL, now=NOW + timedelta(minutes=5))
    assert denied.value.status_code == 429
    assert denied.value.headers["Retry-After"] == "3300"
    assert quota.acquire(PRINCIPAL, now=NOW + timedelta(hours=1))


def test_unknown_transport_keeps_concurrency_lease_until_expiry(quota):
    quota.config = quota.config.model_copy(update={"coach_tokens_per_hour": 3000})
    quota.finish(quota.acquire(PRINCIPAL, now=NOW))
    quota.finish(quota.acquire(PRINCIPAL, now=NOW))
    with pytest.raises(HTTPException) as denied:
        quota.acquire(PRINCIPAL, now=NOW + timedelta(minutes=1))
    assert denied.value.headers["Retry-After"] == "5"
    assert quota.acquire(PRINCIPAL, now=NOW + timedelta(minutes=5))


def failed_trace():
    trace_id, call_id = str(uuid4()), str(uuid4())
    return SimpleNamespace(trace_id=trace_id, status="failed", finished_at=NOW, audit={
        "durable_events": [
            {"event_type": "model.generation.started", "trace_id": trace_id,
             "details": {"call_id": call_id}},
            {"event_type": "model.generation.finished", "trace_id": trace_id,
             "details": {"call_id": call_id, "status": "completed",
                         "input_tokens": 190, "output_tokens": 10}},
            {"event_type": "workflow.failed", "trace_id": trace_id,
             "details": {"error_code": "REVIEW_FAILED"}},
        ],
    })


def test_failed_workflow_with_proven_usage_releases_capacity_and_settles_once(quota):
    trace = failed_trace()
    with Session(quota.engine) as session, session.begin():
        session.add(UserRecord(id="failed-user"))
        session.flush()
        session.add(ChatSessionRecord(id="failed-session", user_id="failed-user", title="Synthetic"))
        session.flush()
        session.add(OrchestrationTraceRecord(trace_id=trace.trace_id, session_id="failed-session",
                                            status=trace.status, finished_at=NOW, audit=trace.audit))
    lease = quota.acquire(PRINCIPAL, now=NOW)
    quota.finish(lease, trace_id=trace.trace_id)
    quota.finish(lease, trace_id=trace.trace_id)
    with Session(quota.engine) as session:
        assert session.get(CoachQuotaLease, lease) is None
        assert session.get(CoachQuotaRecord, principal_key(PRINCIPAL)).charged_tokens == 200
    assert quota.acquire(PRINCIPAL, now=NOW)


@pytest.mark.parametrize("fault", ["inflight", "missing_terminal", "running", "failed_call",
                                   "foreign_trace", "conflicting_replay", "unknown_tokens"])
def test_failed_trace_settlement_requires_complete_trusted_generation_metadata(fault):
    trace = failed_trace()
    events = trace.audit["durable_events"]
    if fault == "inflight":
        events.insert(2, {"event_type": "model.generation.started", "trace_id": trace.trace_id,
                          "details": {"call_id": str(uuid4())}})
    elif fault == "missing_terminal":
        events.pop()
    elif fault == "running":
        trace.status = "running"
    elif fault == "failed_call":
        events[1]["details"]["status"] = "failed"
    elif fault == "foreign_trace":
        events[1]["trace_id"] = str(uuid4())
    elif fault == "conflicting_replay":
        events.insert(2, {**events[1], "details": {**events[1]["details"], "output_tokens": 11}})
    else:
        events[1]["details"]["output_tokens"] = None
    assert known_trace_tokens(trace) is None


def test_identical_replayed_trace_events_are_charged_once():
    trace = failed_trace()
    trace.audit["durable_events"].insert(2, trace.audit["durable_events"][1])
    assert known_trace_tokens(trace) == 200


def test_http_completed_failure_does_not_hold_next_request_capacity(monkeypatch, db_session_factory):
    class Client:
        async def coach(self, _request):
            call_id = str(uuid4())
            record_event("model.generation.started", call_id=call_id)
            record_event("model.generation.finished", call_id=call_id, status="completed",
                         input_tokens=190, output_tokens=10)
            record_event("workflow.failed", error_code="REVIEW_FAILED")
            raise AIServiceUnavailableError()

    monkeypatch.setattr(settings, "coach_concurrent_requests", 1)
    monkeypatch.setattr(settings, "coach_requests_per_minute", 30)
    previous = app.dependency_overrides.get(get_ai_service_client)
    app.dependency_overrides[get_ai_service_client] = Client
    try:
        with TestClient(app) as client:
            headers = {"X-API-Key": settings.api_key}
            for session_id in ("failed-first", "failed-second"):
                result = client.post("/api/coach", headers=headers, json={
                    "user_id": "quota-test-failure", "session_id": session_id,
                    "message": "Explain a budget",
                })
                assert result.status_code == 503
                assert result.headers.get("X-Trace-ID")
        with db_session_factory() as session:
            assert session.scalars(select(CoachQuotaLease)).all() == []
            assert session.scalar(select(CoachQuotaRecord)).charged_tokens == 400
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_ai_service_client, None)
        else:
            app.dependency_overrides[get_ai_service_client] = previous


def test_expired_lease_frees_concurrency_without_refunding_unknown_tokens(quota):
    quota.config = quota.config.model_copy(update={"coach_tokens_per_hour": 3000})
    quota.acquire(PRINCIPAL, now=NOW)
    quota.acquire(PRINCIPAL, now=NOW)
    with pytest.raises(HTTPException):
        quota.acquire(PRINCIPAL, now=NOW)
    later = NOW + timedelta(minutes=5)
    assert quota.acquire(PRINCIPAL, now=later)
    with Session(quota.engine) as session:
        assert session.get(CoachQuotaRecord, principal_key(PRINCIPAL)).charged_tokens == 3000
        assert len(session.scalars(select(CoachQuotaLease)).all()) == 1


def test_identity_and_automation_cannot_evade_limits_using_profiles():
    assert principal_key(PRINCIPAL) == principal_key(AuthenticatedPrincipal("oidc", PRINCIPAL.issuer, PRINCIPAL.subject))
    assert principal_key(PRINCIPAL) != principal_key(AuthenticatedPrincipal("oidc", PRINCIPAL.issuer, "different"))
    assert principal_key(AuthenticatedPrincipal("automation_api_key")) == principal_key(
        AuthenticatedPrincipal("automation_api_key", subject="caller-controlled"))


def test_usage_requires_complete_consistent_audit_and_finish_is_idempotent(quota):
    complete = response()
    assert known_tokens(complete) == 200
    complete.audit["composition_usage_complete"] = False
    assert known_tokens(complete) is None
    complete.audit.pop("composition_usage_complete")
    complete.audit["model_calls"][0]["total_tokens"] = 999
    assert known_tokens(complete) is None
    lease = quota.acquire(PRINCIPAL, now=NOW)
    quota.finish(lease, response())
    quota.finish(lease, response())
    with Session(quota.engine) as session:
        assert session.get(CoachQuotaRecord, principal_key(PRINCIPAL)).charged_tokens == 200


def test_missing_quota_storage_fails_closed(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'empty.db'}")
    try:
        with pytest.raises(HTTPException) as denied:
            CoachQuota(engine, Settings(_env_file=None)).acquire(PRINCIPAL)
        assert denied.value.status_code == 503
    finally:
        engine.dispose()


def test_retention_purges_only_idle_ledgers(quota):
    quota.acquire(PRINCIPAL, now=NOW - timedelta(days=3))
    recent = AuthenticatedPrincipal("oidc", PRINCIPAL.issuer, "active-subject")
    quota.acquire(recent, now=NOW)
    with Session(quota.engine) as session, session.begin():
        assert purge_quota_records(session, NOW) == 1
        assert purge_quota_records(session, NOW) == 0
    with Session(quota.engine) as session:
        assert session.get(CoachQuotaRecord, principal_key(PRINCIPAL)) is None
        assert session.get(CoachQuotaRecord, principal_key(recent)) is not None


def test_http_limit_prevents_model_work_and_chat_creation(monkeypatch, db_session_factory):
    calls = []

    class Client:
        async def coach(self, request):
            calls.append(request.session_id)
            return CoachResponse(session_id=request.session_id, selected_agents=["budget"],
                answer="A budget plans income, spending and savings.", disclaimers=[],
                agent_results=[{"agent": "budget", "summary": "A budget plans income."},
                               {"agent": "risk_compliance", "summary": "Reviewed."}],
                audit={"model_calls": [], "model_call_count": 0})

    monkeypatch.setattr(settings, "coach_requests_per_minute", 1)
    previous = app.dependency_overrides.get(get_ai_service_client)
    app.dependency_overrides[get_ai_service_client] = Client
    try:
        with TestClient(app) as client:
            headers = {"X-API-Key": settings.api_key}
            assert client.put("/api/users/quota-test/profile", headers=headers,
                json={"monthly_income": {"amount": 5000}}).status_code == 200
            data = {"user_id": "quota-test", "session_id": "first", "message": "Explain a budget"}
            assert client.post("/api/coach", headers=headers, json=data).status_code == 200
            # A mismatched conversation owner is rejected before touching the
            # shared quota, even when the same credential can own both profiles.
            ownership_denied = client.post("/api/coach", headers=headers,
                json={**data, "user_id": "other-owner"})
            assert ownership_denied.status_code == 404
            denied = client.post("/api/coach", headers=headers, json={**data, "session_id": "second"})
            assert denied.status_code == 429
            assert int(denied.headers["Retry-After"]) >= 1
        assert calls == ["first"]
        with db_session_factory() as session:
            assert session.get(ChatSessionRecord, "second") is None
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_ai_service_client, None)
        else:
            app.dependency_overrides[get_ai_service_client] = previous
