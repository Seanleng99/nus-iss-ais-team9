import json
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import (
    BLOCKED_EDUCATIONAL_DISCLAIMER,
    BLOCKED_RESPONSE_ANSWER,
    CoachRequest,
    CoachResponse,
)
from app.infrastructure.database import get_db_session
from app.infrastructure.models import (
    ChatMessageRecord,
    ChatSessionRecord,
    OrchestrationTraceRecord,
    UserRecord,
)
from app.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}
POISON = "POISONED_MODEL_RATIONALE"
USER_AUTHORED = "USER_AUTHORED_TEXT"
POISON_SOURCE = {
    "source_id": "poison-source",
    "title": "POISONED_CITATION_TITLE",
    "issuing_organization": "POISONED_CITATION_ORG",
    "canonical_url": "https://poison.example/POISONED_CITATION_URL",
    "published_at": "2026-01-01",
}


class PoisonedBlockedAIServiceClient:
    async def coach(self, request: CoachRequest) -> CoachResponse:
        return CoachResponse.model_validate(
            {
                "session_id": request.session_id,
                "selected_agents": ["budget"],
                "answer": POISON,
                "agent_results": [
                    {
                        "agent": "budget",
                        "summary": POISON,
                        "rationale": [POISON],
                        "confidence": 0.12,
                        "data": {"detail": POISON},
                        "blocked": True,
                        "policy_notes": [
                            POISON,
                            "regulated_advice:tell me exactly what to invest in",
                        ],
                    }
                ],
                "disclaimers": [POISON],
                "sources": [POISON_SOURCE],
                "audit": {
                    "trace_id": f"trace-{request.session_id}",
                    "routing_rationale": [POISON],
                    "model_provider": "fixture",
                    "model_id": "poisoned-fixture",
                    "prompt_set_version": "v3",
                },
                "blocked": True,
            }
        )


def _seed_legacy_blocked_record() -> None:
    session = next(app.dependency_overrides[get_db_session]())
    try:
        session.add(UserRecord(id="legacy-blocked-user"))
        chat = ChatSessionRecord(
            id="legacy-blocked-chat",
            user_id="legacy-blocked-user",
            title="Legacy blocked chat",
        )
        user_message = ChatMessageRecord(
            session_id=chat.id,
            role="user",
            content=USER_AUTHORED,
            position=1,
        )
        message = ChatMessageRecord(
            session_id=chat.id,
            role="assistant",
            content=POISON,
            sources=[POISON_SOURCE],
            position=2,
        )
        session.add(chat)
        session.add_all([user_message, message])
        session.flush()
        session.add(
            OrchestrationTraceRecord(
                trace_id="trace-legacy-blocked",
                session_id=chat.id,
                assistant_message_id=message.id,
                selected_agents=["budget"],
                agent_results=[
                    {
                        "agent": "budget",
                        "summary": POISON,
                        "rationale": [POISON],
                        "confidence": 0.1,
                        "data": {"detail": POISON},
                        "blocked": True,
                        "policy_notes": [
                            POISON,
                            "regulated_advice:tell me exactly what to invest in",
                        ],
                    }
                ],
                audit={"routing_rationale": [POISON], "trace_marker": "legacy"},
                blocked=True,
                model_provider="legacy-fixture",
                model_id="legacy-model",
                prompt_set_version="legacy-v1",
            )
        )
        session.commit()
    finally:
        session.close()


def test_blocked_response_withholds_poison_from_all_backend_surfaces() -> None:
    app.dependency_overrides[get_ai_service_client] = PoisonedBlockedAIServiceClient
    try:
        response = client.post(
            "/api/coach",
            headers=HEADERS,
            json={
                "user_id": "blocked-user",
                "session_id": "blocked-chat",
                "message": "Create a budget",
            },
        )
        history = client.get(
            "/api/users/blocked-user/chat-sessions/blocked-chat", headers=HEADERS
        )
        trace = client.get(
            f"/api/coach/traces/{response.json()['audit']['trace_id']}?user_id=blocked-user",
            headers=HEADERS,
        )
        exported = client.get(
            "/api/users/blocked-user/data-export", headers=HEADERS
        )
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)

    assert response.status_code == 200
    assert response.json()["blocked"] is True
    assert POISON not in json.dumps(response.json())
    assert response.json()["sources"] == []
    assert BLOCKED_EDUCATIONAL_DISCLAIMER in response.json()["disclaimers"]
    assert response.json()["selected_agents"] == ["budget"]
    assert response.json()["audit"]["trace_id"] == response.headers["X-Trace-ID"]
    assert response.json()["agent_results"] == [
        {
            "agent": "budget",
            "summary": "Response withheld by safety controls.",
            "rationale": ["The safety review blocked this response."],
            "confidence": 1.0,
            "data": {},
            "blocked": True,
            "policy_notes": [
                "regulated_advice:tell me exactly what to invest in",
                "response_withheld",
            ],
        }
    ]
    assert history.status_code == 200
    assert POISON not in history.text
    assert history.json()["messages"][1]["sources"] == []
    assert trace.status_code == 200
    assert POISON not in trace.text
    assert trace.json()["trace_id"] == response.headers["X-Trace-ID"]
    assert exported.status_code == 200
    assert POISON not in exported.text
    assert exported.json()["data"]["chat_sessions"][0]["messages"][1]["sources"] == []


def test_legacy_blocked_records_are_sanitized_at_read_boundaries() -> None:
    _seed_legacy_blocked_record()

    history = client.get(
        "/api/users/legacy-blocked-user/chat-sessions/legacy-blocked-chat",
        headers=HEADERS,
    )
    trace = client.get(
        "/api/coach/traces/trace-legacy-blocked?user_id=legacy-blocked-user",
        headers=HEADERS,
    )
    exported = client.get(
        "/api/users/legacy-blocked-user/data-export", headers=HEADERS
    )

    assert history.status_code == 200
    assert POISON not in history.text
    assert history.json()["messages"][1]["sources"] == []
    assert history.json()["messages"][1]["content"].startswith("For your safety")
    assert history.json()["messages"][1]["explanation"]["routing_rationale"] == [
        "The safety review blocked this response."
    ]
    assert trace.status_code == 200
    assert POISON not in trace.text
    assert trace.json()["prompt_set_version"] == "legacy-v1"
    assert exported.status_code == 200
    assert POISON not in exported.text
    assert exported.json()["data"]["chat_sessions"][0]["messages"][1]["sources"] == []

    session = next(app.dependency_overrides[get_db_session]())
    try:
        stored_message = session.get(
            ChatMessageRecord,
            UUID(history.json()["messages"][1]["id"]),
        )
        assert stored_message is not None
        assert stored_message.content == POISON
    finally:
        session.close()


def test_deleting_legacy_blocked_trace_sanitizes_message_before_removal() -> None:
    _seed_legacy_blocked_record()

    deleted = client.delete(
        "/api/coach/traces/trace-legacy-blocked?user_id=legacy-blocked-user",
        headers=HEADERS,
    )
    history = client.get(
        "/api/users/legacy-blocked-user/chat-sessions/legacy-blocked-chat",
        headers=HEADERS,
    )
    exported = client.get(
        "/api/users/legacy-blocked-user/data-export", headers=HEADERS
    )

    assert deleted.status_code == 204
    assert history.status_code == 200
    assert history.json()["messages"][0]["content"] == USER_AUTHORED
    assert history.json()["messages"][1]["content"] == BLOCKED_RESPONSE_ANSWER
    assert history.json()["messages"][1]["sources"] == []
    assert POISON not in history.text
    assert exported.status_code == 200
    assert exported.json()["data"]["chat_sessions"][0]["messages"][0]["content"] == (
        USER_AUTHORED
    )
    assert exported.json()["data"]["chat_sessions"][0]["messages"][1]["content"] == (
        BLOCKED_RESPONSE_ANSWER
    )
    assert exported.json()["data"]["chat_sessions"][0]["messages"][1]["sources"] == []
    assert POISON not in exported.text
