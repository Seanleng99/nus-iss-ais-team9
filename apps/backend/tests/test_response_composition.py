import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.clients.ai_service import AIServiceClient, AIServiceUnavailableError
from app.core.config import Settings
from app.core.run_trace import active_run
from app.domain.schemas import CoachResponse, InternalCoachRequest
from app.services.response_composition import action_outcome, compose_backend_response


def response():
    return CoachResponse(session_id="chat", selected_agents=["spending"],
        answer="Saved SGD 12.00 for Lunch.", agent_results=[], disclaimers=[],
        audit={"source": "transaction_capture", "trace_id": "trace"})


REQUEST = InternalCoachRequest(user_id="user", session_id="chat", message="Record my lunch.", message_position=1)


@pytest.mark.parametrize("timed_out", [True, False])
def test_composition_transport_failure_preserves_authoritative_action_result_and_known_usage(timed_out):
    class Client:
        async def compose(self, *args):
            raise AIServiceUnavailableError(timed_out=timed_out)
    original = response()
    calls = [{"component": "router", "input_tokens": 10, "output_tokens": 5, "status": "completed"}]
    original.audit.update(model_calls=calls, model_call_count=1, model_input_tokens=10, model_output_tokens=5)
    result = asyncio.run(compose_backend_response(Client(), REQUEST, original))
    assert result.answer == "Saved SGD 12.00 for Lunch."
    assert result.audit["post_action_composed"] is False
    assert result.audit["backend_outcomes"][0]["authority"] == "authenticated_backend"
    assert result.audit["composition_usage_complete"] is False
    assert result.audit["model_calls"] == calls
    assert result.audit["model_call_count"] == 1
    assert result.audit["model_input_tokens"] == 10 and result.audit["model_output_tokens"] == 5


@pytest.mark.parametrize("update", [{"session_id": "other-chat"}, {"selected_agents": []},
                                    {"audit": {"trace_id": "other-trace"}}, {"blocked": True}])
def test_composition_cannot_change_owned_identity_or_selected_evidence(update):
    class Client:
        async def compose(self, request, original, outcomes):
            return original.model_copy(update=update)
    result = asyncio.run(compose_backend_response(Client(), REQUEST, response()))
    assert result.session_id == "chat"
    assert result.audit["trace_id"] == "trace"
    assert result.answer == "Saved SGD 12.00 for Lunch."


def test_reviewed_natural_response_is_returned_with_outcome_audit():
    class Client:
        async def compose(self, request, original, outcomes):
            return original.model_copy(update={"answer": "Lunch is recorded: SGD 12.00.",
                "audit": {**original.audit, "post_action_composed": True}})
    result = asyncio.run(compose_backend_response(Client(), REQUEST, response()))
    assert result.answer == "Lunch is recorded: SGD 12.00."
    assert result.audit["post_action_composed"] is True
    assert result.audit["post_action_duration_ms"] >= 0


def test_blocked_response_never_reaches_composition():
    class Client:
        async def compose(self, *args):
            pytest.fail("Blocked response reached composer")
    original = response().model_copy(update={"blocked": True})
    assert asyncio.run(compose_backend_response(Client(), REQUEST, original)) is original


def test_composition_total_deadline_preserves_saved_result(monkeypatch):
    original_client = httpx.AsyncClient
    started = []

    async def slow_response(request):
        started.append(True)
        await asyncio.sleep(0.1)
        return httpx.Response(200, json=response().model_dump(mode="json"))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(slow_response), **kwargs))
    client = AIServiceClient(Settings(AI_SERVICE_COMPOSITION_TIMEOUT_SECONDS=0.01))
    original = response()
    original.audit.update(model_call_count=1, model_input_tokens=11, model_output_tokens=7)
    result = asyncio.run(compose_backend_response(client, REQUEST, original))
    assert started == [True]
    assert result.answer == "Saved SGD 12.00 for Lunch."
    assert result.audit["composition_fallback_code"] == "COMPOSITION_UNAVAILABLE"
    assert result.audit["post_action_duration_ms"] < 100
    assert result.audit["composition_usage_complete"] is False
    assert result.audit["model_call_count"] == 1
    assert result.audit["model_input_tokens"] == 11 and result.audit["model_output_tokens"] == 7


@pytest.mark.parametrize("composed", [True, False])
def test_returned_validated_composition_or_audited_fallback_preserves_complete_call_accounting(composed):
    calls = [{"component": "response_composer", "input_tokens": 30, "output_tokens": 10,
              "status": "completed"}]
    class Client:
        async def compose(self, request, original, outcomes):
            return original.model_copy(update={"audit": {
                **original.audit, "post_action_composed": composed, "model_calls": calls,
                "model_call_count": 1, "model_input_tokens": 30, "model_output_tokens": 10,
                **({} if composed else {"composition_fallback_code": "ACTION_COMPOSITION_UNGROUNDED"}),
            }})
    result = asyncio.run(compose_backend_response(Client(), REQUEST, response()))
    assert result.audit.get("composition_usage_complete") is not False
    assert result.audit["post_action_composed"] is composed
    assert result.audit["model_calls"] == calls
    assert result.audit["model_input_tokens"] == 30 and result.audit["model_output_tokens"] == 10


def test_outcome_status_uses_backend_state_and_never_boolean_routing_flags():
    value = response()
    value.audit.update(goal_capture=True, action_status="cancelled")
    assert action_outcome("goal", value)["status"] == "cancelled"
    del value.audit["action_status"]
    assert action_outcome("goal", value)["status"] == "reviewed_result"


def test_primary_stream_deadline_expires_despite_receiving_events(monkeypatch):
    original_client = httpx.AsyncClient
    received = []

    class Events(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(20):
                await asyncio.sleep(0.005)
                yield b'{"type":"event","event":{}}\n'

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200,
            headers={"content-type": "application/x-ndjson"}, stream=Events())), **kwargs))
    client = AIServiceClient(Settings(AI_SERVICE_TIMEOUT_SECONDS=0.03))
    token = active_run.set(SimpleNamespace(trace_id="test-trace", append=received.append))
    try:
        with pytest.raises(AIServiceUnavailableError) as failure:
            asyncio.run(client.coach(REQUEST))
        assert failure.value.timed_out and len(received) < 20
    finally:
        active_run.reset(token)


def test_mixed_goal_preview_and_spending_query_have_independent_authoritative_statuses():
    from fastapi.testclient import TestClient

    from app.api.routes import get_ai_service_client
    from app.core.config import settings
    from app.main import app

    class Client:
        async def coach(self, request):
            return CoachResponse(session_id=request.session_id, selected_agents=["goal_strategy", "spending"],
                answer="Draft and query", disclaimers=[], audit={}, agent_results=[
                    {"agent": "goal_strategy", "summary": "Goal draft", "data": {"goal_draft": {
                        "action": "create", "name": "Emergency fund", "currency": "SGD",
                        "target_amount": 1200, "current_amount": 0, "target_months": 12}}},
                    {"agent": "spending", "summary": "Query", "data": {"spending_draft": {
                        "action": "query", "query_date": "2026-09-24"}}},
                ])

    app.dependency_overrides[get_ai_service_client] = Client
    try:
        result = TestClient(app).post("/api/coach", headers={"X-API-Key": settings.api_key}, json={
            "user_id": "mixed-status-user", "session_id": "mixed-status-chat",
            "message": "Prepare an emergency fund goal for review and show my expenses for 24 September.",
        })
        assert result.status_code == 200, result.text
        outcomes = {item["operation"]: item for item in result.json()["audit"]["backend_outcomes"]}
        assert outcomes["goal"]["status"] == "preview"
        assert outcomes["spending"]["status"] == "read_only_query"
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)
