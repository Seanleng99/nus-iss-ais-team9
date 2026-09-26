import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.infrastructure.models import OrchestrationTraceRecord
from app.infrastructure.repositories import SQLAlchemyOrchestrationTraceRepository
from app.main import app

HEADERS = {"X-API-Key": settings.api_key}
PAYLOAD = {
    "user_id": "trace-owner",
    "session_id": "trace-chat",
    "message": "private question 43210",
}


def event(trace_id, event_type="routing.completed", **details):
    return {
        "type": "event",
        "event": {
            "trace_id": trace_id,
            "event_id": str(uuid4()),
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "task_id": "task-budget",
            "details": {"selected_agents": ["budget"], **details},
        },
    }


def answer(trace_id, blocked=False):
    return {
        "type": "response",
        "response": {
            "session_id": "trace-chat",
            "selected_agents": ["budget"],
            "answer": "private generated answer",
            "agent_results": [],
            "disclaimers": [],
            "sources": [],
            "audit": {"trace_id": trace_id},
            "blocked": blocked,
        },
    }


def install(monkeypatch, db_session_factory, outcome, *, blocked=False):
    sent = []

    class Frames(httpx.AsyncByteStream):
        async def __aiter__(self):
            trace_id = sent[0]
            # The run exists durably before AI generation starts.
            with db_session_factory() as session:
                record = session.get(OrchestrationTraceRecord, trace_id)
                assert record.status == "running"
                assert record.assistant_message_id is None
            first = event(
                trace_id, question="private forbidden payload", rationale="private reason"
            )
            yield (json.dumps(first) + "\n").encode()
            # A different DB session can see the decision before the next frame arrives.
            with db_session_factory() as session:
                record = session.get(OrchestrationTraceRecord, trace_id)
                saved = record.audit["durable_events"]
                assert len(saved) == 1
                assert saved[0]["event_id"] == first["event"]["event_id"]
                assert "question" not in saved[0]["details"]
                assert "rationale" not in saved[0]["details"]
            if outcome == "timeout":
                raise httpx.ReadTimeout("private exception")
            if outcome == "truncated":
                return
            if outcome in {"error", "agent_timeout"}:
                frame = {
                    "type": "error",
                    "code": "AGENT_TIMEOUT" if outcome == "agent_timeout" else "WORKFLOW_FAILED",
                }
            elif outcome == "malformed":
                frame = ["private malformed frame"]
            elif outcome == "write_failure":
                frame = event(trace_id, "task.started")
            elif outcome == "mismatch":
                frame = answer(str(uuid4()))
            else:
                # Duplicate delivery is idempotent.
                yield (json.dumps(first) + "\n").encode()
                frame = answer(trace_id, blocked)
            yield (json.dumps(frame) + "\n").encode()

    def respond(request):
        assert request.url.path == "/coach/stream"
        sent.append(request.headers["X-Workflow-ID"])
        return httpx.Response(
            200, headers={"Content-Type": "application/x-ndjson"}, stream=Frames()
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: AsyncClient(transport=httpx.MockTransport(respond), **kw)
    )
    return sent


@pytest.mark.parametrize(
    "outcome,expected",
    [
        ("success", "completed"),
        ("error", "failed"),
        ("timeout", "timed_out"),
        ("agent_timeout", "timed_out"),
        ("truncated", "failed"),
        ("malformed", "failed"),
        ("mismatch", "failed"),
    ],
)
def test_incremental_trace_survives_failure(monkeypatch, db_session_factory, outcome, expected):
    sent = install(monkeypatch, db_session_factory, outcome)
    client = TestClient(app)
    response = client.post("/api/coach", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == (200 if outcome == "success" else 503)
    trace_id = response.headers["X-Trace-ID"]
    assert trace_id == sent[0]
    trace = client.get(f"/api/coach/traces/{trace_id}?user_id=trace-owner", headers=HEADERS)
    assert trace.status_code == 200
    data = trace.json()
    assert data["status"] == expected
    assert data["finished_at"]
    assert len(data["audit"]["durable_events"]) == 1
    assert bool(data["assistant_message_id"]) == (outcome == "success")
    assert "private forbidden" not in trace.text
    assert (
        client.get(f"/api/coach/traces/{trace_id}?user_id=other-owner", headers=HEADERS).status_code
        == 404
    )
    export = client.get("/api/users/trace-owner/data-export", headers=HEADERS).json()
    if outcome != "success":
        assert export["data"]["incomplete_orchestration_traces"][0]["trace_id"] == trace_id
    assert (
        client.delete(
            f"/api/coach/traces/{trace_id}?user_id=trace-owner", headers=HEADERS
        ).status_code
        == 204
    )
    assert (
        client.get(f"/api/coach/traces/{trace_id}?user_id=trace-owner", headers=HEADERS).status_code
        == 404
    )


def test_blocked_run_keeps_metadata_but_withholds_answer(monkeypatch, db_session_factory):
    install(monkeypatch, db_session_factory, "success", blocked=True)
    client = TestClient(app)
    response = client.post("/api/coach", headers=HEADERS, json=PAYLOAD)
    trace_id = response.headers["X-Trace-ID"]
    trace = client.get(f"/api/coach/traces/{trace_id}?user_id=trace-owner", headers=HEADERS)
    assert trace.json()["status"] == "blocked"
    assert "private generated answer" not in response.text + trace.text


@pytest.mark.parametrize("recovery_write_fails", [False, True])
def test_later_database_failure_preserves_committed_events(
    monkeypatch, db_session_factory, caplog, recovery_write_fails
):
    sent = install(monkeypatch, db_session_factory, "write_failure")
    original = Session.commit
    failed = False

    def commit(session):
        nonlocal failed
        records = [
            r for r in session.identity_map.values() if isinstance(r, OrchestrationTraceRecord)
        ]
        if any(len(r.audit.get("durable_events", [])) == 2 for r in records) or (
            failed and recovery_write_fails
        ):
            failed = True
            raise OperationalError("private SQL", {"secret": "private database payload"}, None)
        return original(session)

    with monkeypatch.context() as scoped:
        scoped.setattr(Session, "commit", commit)
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/coach", headers=HEADERS, json=PAYLOAD
        )
    assert response.status_code == 500
    with db_session_factory() as session:
        record = session.get(OrchestrationTraceRecord, sent[0])
        assert record.status == ("running" if recovery_write_fails else "failed")
        assert len(record.audit["durable_events"]) == 1
        if recovery_write_fails:
            record.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
    trace = TestClient(app).get(f"/api/coach/traces/{sent[0]}?user_id=trace-owner", headers=HEADERS)
    assert trace.json()["status"] == ("abandoned" if recovery_write_fails else "failed")
    assert "private database payload" not in caplog.text
    if recovery_write_fails:
        assert "trace.persistence.failed" in caplog.text


def test_failed_runs_follow_retention_and_chat_deletion(monkeypatch, db_session_factory):
    sent = install(monkeypatch, db_session_factory, "error")
    client = TestClient(app)
    client.post("/api/coach", headers=HEADERS, json=PAYLOAD)
    with db_session_factory() as session:
        record = session.get(OrchestrationTraceRecord, sent[0])
        record.created_at = datetime.now(UTC) - timedelta(days=31)
        session.commit()
        assert (
            SQLAlchemyOrchestrationTraceRepository(session).delete_expired(
                datetime.now(UTC) - timedelta(days=30)
            )
            == 1
        )
        session.commit()
    sent.clear()
    client.post("/api/coach", headers=HEADERS, json=PAYLOAD)
    response = client.delete("/api/users/trace-owner/chat-sessions/trace-chat", headers=HEADERS)
    assert response.status_code == 204
    with db_session_factory() as session:
        assert session.scalar(select(OrchestrationTraceRecord)) is None


def test_real_ai_event_protocol_round_trip(monkeypatch, db_session_factory):
    """Separate interpreters avoid the services' identical `app` package names."""
    import subprocess
    import sys
    from pathlib import Path

    ai_root = Path(__file__).resolve().parents[2] / "ai-service"
    script = """
import asyncio, json, sys
from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.core.trace_stream import stream_run
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
payload = json.load(sys.stdin)
orchestrator = AgentOrchestrator(config=Settings(MODEL_PROVIDER='local_fixture'), gateway=LocalFixtureModelGateway())
async def main():
    async for frame in stream_run(orchestrator, CoachRequest.model_validate(payload['request']), payload['trace_id']):
        print(frame, end='')
asyncio.run(main())
"""

    def respond(request):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", script],
            cwd=ai_root,
            input=json.dumps(
                {
                    "trace_id": request.headers["X-Workflow-ID"],
                    "request": json.loads(request.content),
                }
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        return httpx.Response(
            200, headers={"Content-Type": "application/x-ndjson"}, text=result.stdout
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: AsyncClient(transport=httpx.MockTransport(respond), **kw)
    )
    client = TestClient(app)
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={
            **PAYLOAD,
            "message": "Build a budget",
            "snapshot": {"monthly_income": {"amount": 5000}},
        },
    )
    assert response.status_code == 200
    trace_id = response.headers["X-Trace-ID"]
    trace = client.get(f"/api/coach/traces/{trace_id}?user_id=trace-owner", headers=HEADERS).json()
    assert trace["status"] == "completed"
    assert trace["model_provider"] == "local_fixture"
    events = trace["audit"]["durable_events"]
    assert any(item["event_type"] == "task.completed" for item in events)
    for call in trace["audit"]["model_calls"]:
        matching = [e for e in events if e["details"].get("call_id") == call["call_id"]]
        assert len(matching) == 2
        assert all(e["trace_id"] == trace_id for e in matching)
        if call.get("task_id"):
            assert all(e["task_id"] == call["task_id"] for e in matching)


def test_final_chat_commit_failure_keeps_trace_without_partial_messages(
    monkeypatch, db_session_factory
):
    from app.infrastructure.models import ChatMessageRecord

    sent = install(monkeypatch, db_session_factory, "success")
    original = Session.commit
    failed = False

    def commit(session):
        nonlocal failed
        if not failed and any(
            isinstance(record, OrchestrationTraceRecord) and record.status == "completed"
            for record in session.identity_map.values()
        ):
            failed = True
            raise OperationalError("private SQL", {}, None)
        return original(session)

    monkeypatch.setattr(Session, "commit", commit)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/coach", headers=HEADERS, json=PAYLOAD
    )
    assert response.status_code == 500
    with db_session_factory() as session:
        record = session.get(OrchestrationTraceRecord, sent[0])
        assert record.status == "failed"
        assert record.assistant_message_id is None
        assert len(record.audit["durable_events"]) == 1
        assert session.scalar(select(ChatMessageRecord)) is None


def test_overall_timeout_preserves_trace_even_when_transport_does_not_timeout(
    monkeypatch, db_session_factory
):
    import asyncio

    monkeypatch.setattr(settings, "ai_service_timeout_seconds", 0.05)

    class WaitingFrames(httpx.AsyncByteStream):
        def __init__(self, trace_id):
            self.trace_id = trace_id

        async def __aiter__(self):
            yield (json.dumps(event(self.trace_id)) + "\n").encode()
            await asyncio.sleep(1)
            yield (json.dumps(answer(self.trace_id)) + "\n").encode()

    def respond(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "application/x-ndjson"},
            stream=WaitingFrames(request.headers["X-Workflow-ID"]),
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: AsyncClient(transport=httpx.MockTransport(respond), **kw)
    )
    client = TestClient(app)
    response = client.post("/api/coach", headers=HEADERS, json=PAYLOAD)
    assert response.status_code == 503
    trace_id = response.headers["X-Trace-ID"]
    trace = client.get(f"/api/coach/traces/{trace_id}?user_id=trace-owner", headers=HEADERS).json()
    assert trace["status"] == "timed_out"
    assert len(trace["audit"]["durable_events"]) == 1
