import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api import routes
from app.api.financial_schemas import GoalCreate
from app.core.config import settings
from app.core.run_trace import active_run
from app.domain.schemas import CoachResponse
from app.infrastructure.models import FinancialGoalRecord, OrchestrationTraceRecord
from app.infrastructure.repositories import SQLAlchemyGoalRepository
from app.main import app


@pytest.mark.parametrize("fail_final_commit", [False, True])
def test_local_confirmation_composition_never_commits_action_before_final_exchange(
    monkeypatch, db_session_factory, fail_final_commit
):
    sent = []
    commits = []
    original_commit = Session.commit

    def confirm(session, request):
        session.info["action_started"] = True
        SQLAlchemyGoalRepository(session).create(
            request.user_id,
            GoalCreate.model_validate(
                {
                    "name": "Emergency fund",
                    "target_amount": {"amount": 1200},
                    "current_amount": {"amount": 0},
                    "target_months": 12,
                }
            ),
        )
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["goal_strategy"],
            answer="Saved the goal",
            agent_results=[],
            disclaimers=[],
            audit={"source": "goal_confirmation", "action_status": "saved"},
        )

    def commit(session):
        if session.info.get("action_started"):
            record = next(
                r for r in session.identity_map.values() if isinstance(r, OrchestrationTraceRecord)
            )
            commits.append(record.status)
            assert record.status in {"completed", "failed"}, (
                "trace persistence committed a pending financial action"
            )
            if fail_final_commit and record.status == "completed":
                raise OperationalError("PRIVATE commit failure", {}, None)
        return original_commit(session)

    class Frames(httpx.AsyncByteStream):
        async def __aiter__(self):
            trace_id, reply = sent[-1]
            event = {
                "event_id": str(uuid4()),
                "trace_id": trace_id,
                "event_type": "composition.started",
                "timestamp": datetime.now(UTC).isoformat(),
                "details": {"phase": "post_action", "prompt": "PRIVATE"},
            }
            yield (json.dumps({"type": "event", "event": event}) + "\n").encode()
            assert active_run.get().pending
            assert commits == []
            reply["audit"]["post_action_composed"] = True
            yield (json.dumps({"type": "response", "response": reply}) + "\n").encode()

    def respond(request):
        assert request.url.path == "/coach/compose/stream"
        payload = json.loads(request.content)
        assert request.headers["X-Workflow-ID"] == payload["response"]["audit"]["trace_id"]
        sent.append((request.headers["X-Workflow-ID"], payload["response"]))
        return httpx.Response(
            200, headers={"Content-Type": "application/x-ndjson"}, stream=Frames()
        )

    monkeypatch.setattr(routes, "handle_goal_confirmation", confirm)
    monkeypatch.setattr(Session, "commit", commit)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: AsyncClient(transport=httpx.MockTransport(respond), **kw)
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/coach",
        headers={"X-API-Key": settings.api_key},
        json={
            "user_id": "trace-actions",
            "session_id": "trace-actions-chat",
            "message": "Confirm goal",
        },
    )
    assert response.status_code == (500 if fail_final_commit else 200)
    trace_id = sent[0][0]
    with db_session_factory() as session:
        record = session.get(OrchestrationTraceRecord, trace_id)
        assert record.status == ("failed" if fail_final_commit else "completed")
        assert len(session.scalars(select(FinancialGoalRecord)).all()) == (
            0 if fail_final_commit else 1
        )
        events = record.audit["durable_events"]
        assert any(
            e["event_type"] == "backend.handler.selected"
            and e["details"]["handler"] == "goal_confirmation"
            for e in events
        )
        assert any(e["event_type"] == "composition.started" for e in events)
        assert (
            any(e["event_type"] == "backend.persistence.completed" for e in events)
            is not fail_final_commit
        )
        assert "PRIVATE" not in json.dumps(events)
    assert commits == (["completed", "failed"] if fail_final_commit else ["completed"])
