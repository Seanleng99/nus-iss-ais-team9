import json
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core.run_trace import event_sink, workflow_id
from app.main import app, get_orchestrator
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class FailingGateway(LocalFixtureModelGateway):
    def generate(self, **kwargs):
        raise ModelGatewayError("private model error")


@pytest.mark.parametrize("failed", [False, True])
def test_stream_emits_linked_content_free_events_and_terminal_frame(failed, caplog):
    caplog.set_level(logging.INFO, logger="service")
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=FailingGateway() if failed else LocalFixtureModelGateway(),
    )
    app.dependency_overrides[get_orchestrator] = lambda: orchestrator
    trace_id = str(uuid4())
    try:
        response = TestClient(app).post(
            "/coach/stream",
            headers={"X-API-Key": settings.api_key, "X-Workflow-ID": trace_id},
            json={
                "user_id": "private-user",
                "session_id": "private-session",
                "message": "Build a budget so I can save for a home goal",
                "snapshot": {"monthly_income": {"amount": 5000}},
            },
        )
    finally:
        app.dependency_overrides.pop(get_orchestrator, None)
    assert response.status_code == 200
    frames = [json.loads(line) for line in response.text.splitlines()]
    assert frames[-1]["type"] == ("error" if failed else "response")
    events = [item["event"] for item in frames if item["type"] == "event"]
    assert events
    assert all(item["trace_id"] == trace_id for item in events)
    assert len({item["event_id"] for item in events}) == len(events)
    serialized = json.dumps(events)
    for private in ("private-user", "private-session", "Build a budget", "private model error"):
        assert private not in serialized
    logs = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name.startswith("service.")
    ]
    for item in events:
        assert any(log.get("event_id") == item["event_id"] for log in logs)
    if failed:
        assert any(item["event_type"] == "workflow.failed" for item in events)
    else:
        result = frames[-1]["response"]
        assert result["audit"]["trace_id"] == trace_id
        calls = result["audit"]["model_calls"]
        assert calls and all(call["call_id"] and call["span_id"] for call in calls)
        task_ids = {item["task_id"] for item in events if item["event_type"] == "task.started"}
        specialist_calls = [call for call in calls if call.get("task_id")]
        assert specialist_calls
        assert all(
            call["task_id"] in task_ids and call["attempt"] >= 1 for call in specialist_calls
        )
        assert all(
            any(item["details"].get("call_id") == call["call_id"] for item in events)
            for call in calls
        )
    assert workflow_id.get() is None
    assert event_sink.get() is None


def test_stream_requires_service_authentication_and_valid_workflow_id():
    client = TestClient(app)
    payload = {"user_id": "u", "session_id": "s", "message": "Budget"}
    assert client.post("/coach/stream", json=payload).status_code == 401
    assert (
        client.post(
            "/coach/stream",
            headers={"X-API-Key": settings.api_key, "X-Workflow-ID": "untrusted text"},
            json=payload,
        ).status_code
        == 422
    )


def test_stream_disconnect_releases_worker_and_rejects_late_events(monkeypatch):
    import asyncio
    from threading import BoundedSemaphore, Event

    from app.core import trace_stream
    from app.core.run_trace import emit
    from app.core.schemas import CoachRequest

    workers = BoundedSemaphore(1)
    monkeypatch.setattr(trace_stream, "_workers", workers)
    resume = Event()
    rejected = Event()

    class WaitingOrchestrator:
        def handle(self, request):
            emit({"event_type": "started"})
            resume.wait(timeout=2)
            try:
                emit({"event_type": "late"})
            except trace_stream.TraceStreamClosed:
                rejected.set()
                raise

    async def check():
        stream = trace_stream.stream_run(
            WaitingOrchestrator(),
            CoachRequest(user_id="u", session_id="s", message="Budget"),
            str(uuid4()),
        )
        assert json.loads(await anext(stream))["type"] == "event"
        await stream.aclose()
        resume.set()
        assert await asyncio.to_thread(workers.acquire, True, 2)
        workers.release()
        assert rejected.is_set()

    asyncio.run(check())


def test_stream_capacity_is_bounded(monkeypatch):
    import asyncio
    from threading import BoundedSemaphore

    from app.core import trace_stream

    workers = BoundedSemaphore(1)
    workers.acquire()
    monkeypatch.setattr(trace_stream, "_workers", workers)

    async def check():
        frames = [
            json.loads(frame) async for frame in trace_stream.stream_run(None, None, str(uuid4()))
        ]
        assert frames == [{"type": "error", "code": "WORKFLOW_CAPACITY"}]

    asyncio.run(check())
