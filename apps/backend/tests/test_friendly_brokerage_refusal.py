"""Exact safe brokerage refusals survive every blocked-response boundary."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from language_fixtures import language_case
from sqlalchemy import select

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import (
    BLOCKED_RESPONSE_ANSWER,
    BLOCKED_RESPONSE_ANSWER_ZH,
    BROKERAGE_RESPONSE_ANSWER,
    BROKERAGE_RESPONSE_ANSWER_ZH,
    SAFE_REFUSAL_TEMPLATES,
    CoachRequest,
    CoachResponse,
    blocked_response_answer,
)
from app.infrastructure.models import (
    ChatMessageRecord,
    ChatSessionRecord,
    OrchestrationTraceRecord,
    UserRecord,
)
from app.jobs.purge_orchestration_traces import purge_expired_traces
from app.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}
ENGLISH_REQUEST = "Can you log in to my brokerage account and buy an ETF for me?"
CHINESE_REQUEST = language_case("friendly_brokerage_refusal.chinese_request")
POISON = "POISONED_AGENT_OR_TRACE_CONTENT"
POISON_SOURCE = {
    "source_id": "poison-source",
    "title": "POISONED_SOURCE_TITLE",
    "issuing_organization": "POISONED_SOURCE_ORG",
    "canonical_url": "https://poison.example/fake",
    "published_at": "2026-01-01",
}


class BrokerageBlockedAIServiceClient:
    def __init__(self, answer: str, claimed_language: str):
        self.answer = answer
        self.claimed_language = claimed_language

    async def coach(self, request: CoachRequest) -> CoachResponse:
        return CoachResponse.model_validate({
            "session_id": request.session_id,
            "selected_agents": ["budget"],
            "answer": self.answer,
            "agent_results": [{
                "agent": "budget",
                "summary": POISON,
                "rationale": [POISON],
                "confidence": 0.2,
                "data": {"private_detail": POISON},
                "blocked": True,
                "policy_notes": [POISON],
            }],
            "disclaimers": [POISON],
            "sources": [POISON_SOURCE],
            "audit": {
                "trace_id": f"trace-{request.session_id}",
                "response_language": self.claimed_language,
                "routing_rationale": [POISON],
                "model_provider": "fixture",
                "model_id": "brokerage-refusal-fixture",
            },
            "blocked": True,
        })


@pytest.mark.parametrize("answer", [
    BROKERAGE_RESPONSE_ANSWER,
    BROKERAGE_RESPONSE_ANSWER_ZH,
])
@pytest.mark.parametrize(
    ("response_language", "expected"),
    [
        ("English", BROKERAGE_RESPONSE_ANSWER),
        ("Chinese", BROKERAGE_RESPONSE_ANSWER_ZH),
    ],
)
def test_exact_approved_brokerage_refusal_renders_in_requested_language(
    answer: str, response_language: str, expected: str,
) -> None:
    assert blocked_response_answer(
        response_language=response_language, answer=answer
    ) == expected


@pytest.mark.parametrize(
    ("answer", "response_language", "expected"),
    [
        (BROKERAGE_RESPONSE_ANSWER + " " + POISON, "English", BLOCKED_RESPONSE_ANSWER),
        (BROKERAGE_RESPONSE_ANSWER_ZH + " " + POISON, "Chinese", BLOCKED_RESPONSE_ANSWER_ZH),
        (POISON, "English", BLOCKED_RESPONSE_ANSWER),
        (POISON, "Chinese", BLOCKED_RESPONSE_ANSWER_ZH),
    ],
)
def test_modified_or_unknown_refusal_falls_back_to_generic(answer, response_language, expected):
    assert blocked_response_answer(
        response_language=response_language, answer=answer
    ) == expected


@pytest.mark.parametrize(
    ("message", "claimed_language", "answer", "expected"),
    [
        row for english, chinese in SAFE_REFUSAL_TEMPLATES for row in (
            (ENGLISH_REQUEST, "Chinese", english, english),
            (CHINESE_REQUEST, "English", english, chinese),
        )
    ],
)
def test_live_history_export_and_trace_delete_keep_safe_localized_refusal(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    claimed_language: str,
    answer: str,
    expected: str,
) -> None:
    user_id = "friendly-brokerage-user"
    session_id = "friendly-brokerage-chat"
    monkeypatch.setitem(
        app.dependency_overrides,
        get_ai_service_client,
        lambda: BrokerageBlockedAIServiceClient(
            answer, claimed_language
        ),
    )

    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": user_id, "session_id": session_id, "message": message,
              "response_locale": "zh-Hans" if message == CHINESE_REQUEST else "en"},
    )
    assert response.status_code == 200
    trace_id = response.json()["audit"]["trace_id"]
    assert response.headers["X-Trace-ID"] == trace_id
    history = client.get(
        f"/api/users/{user_id}/chat-sessions/{session_id}", headers=HEADERS
    )
    trace = client.get(
        f"/api/coach/traces/{trace_id}?user_id={user_id}", headers=HEADERS
    )
    exported = client.get(f"/api/users/{user_id}/data-export", headers=HEADERS)

    assert response.status_code == history.status_code == trace.status_code == exported.status_code == 200
    assert response.json()["blocked"] is True
    assert response.json()["answer"] == expected
    assert response.json()["sources"] == []
    assert history.json()["messages"][1]["content"] == expected
    assert history.json()["messages"][1]["sources"] == []
    assert trace.json()["blocked"] is True
    export_message = exported.json()["data"]["chat_sessions"][0]["messages"][1]
    assert export_message["content"] == expected
    assert export_message["sources"] == []
    assert POISON not in json.dumps(
        [response.json(), history.json(), trace.json(), exported.json()]
    )

    deleted = client.delete(
        f"/api/coach/traces/{trace_id}?user_id={user_id}", headers=HEADERS
    )
    after_delete = client.get(
        f"/api/users/{user_id}/chat-sessions/{session_id}", headers=HEADERS
    )
    export_after_delete = client.get(f"/api/users/{user_id}/data-export", headers=HEADERS)
    assert deleted.status_code == 204
    assert after_delete.json()["messages"][1]["content"] == expected
    assert export_after_delete.json()["data"]["chat_sessions"][0]["messages"][1]["content"] == expected
    assert POISON not in after_delete.text + export_after_delete.text


def test_expired_trace_purge_preserves_only_exact_brokerage_templates(db_session_factory):
    now = datetime.now(UTC)
    rows = [
        ("expired-refusal-en", BROKERAGE_RESPONSE_ANSWER, "English", BROKERAGE_RESPONSE_ANSWER),
        ("expired-refusal-zh", BROKERAGE_RESPONSE_ANSWER_ZH, "Chinese", BROKERAGE_RESPONSE_ANSWER_ZH),
        ("expired-localize", BROKERAGE_RESPONSE_ANSWER_ZH, "English", BROKERAGE_RESPONSE_ANSWER),
        ("expired-appended-en", BROKERAGE_RESPONSE_ANSWER + POISON, "English", BLOCKED_RESPONSE_ANSWER),
        ("expired-appended-zh", BROKERAGE_RESPONSE_ANSWER_ZH + POISON, "Chinese", BLOCKED_RESPONSE_ANSWER_ZH),
        ("expired-poison-en", POISON, "English", BLOCKED_RESPONSE_ANSWER),
        ("expired-poison-zh", POISON, "Chinese", BLOCKED_RESPONSE_ANSWER_ZH),
    ]
    for index, (english, chinese) in enumerate(SAFE_REFUSAL_TEMPLATES):
        rows.extend([
            (f"safe-{index}-en", english, "English", english),
            (f"safe-{index}-zh", english, "Chinese", chinese),
            (f"poison-{index}", english + POISON, "English", BLOCKED_RESPONSE_ANSWER),
        ])
    message_ids = {}
    with db_session_factory() as session:
        session.add(UserRecord(id="expired-refusal-user"))
        chat = ChatSessionRecord(
            id="expired-refusal-chat",
            user_id="expired-refusal-user",
            title="Expired blocked responses",
        )
        session.add(chat)
        for position, (trace_id, answer, language, _) in enumerate(rows, start=1):
            message = ChatMessageRecord(
                id=uuid4(),
                session_id=chat.id,
                role="assistant",
                content=answer,
                sources=[POISON_SOURCE],
                position=position,
            )
            session.add(message)
            session.flush()
            message_ids[trace_id] = message.id
            session.add(OrchestrationTraceRecord(
                trace_id=trace_id,
                session_id=chat.id,
                assistant_message_id=message.id,
                selected_agents=["budget"],
                agent_results=[],
                audit={"response_language": language},
                blocked=True,
                created_at=now - timedelta(days=31),
            ))
        session.commit()

        deleted_count, _ = purge_expired_traces(session, 30, now=now)
        stored_messages = {}
        for trace_id, message_id in message_ids.items():
            message = session.get(ChatMessageRecord, message_id)
            stored_messages[trace_id] = (message.content, message.sources)
        remaining = session.scalars(select(OrchestrationTraceRecord.trace_id)).all()

    assert deleted_count == len(rows)
    assert remaining == []
    for trace_id, _, _, expected in rows:
        assert stored_messages[trace_id] == (expected, [])
