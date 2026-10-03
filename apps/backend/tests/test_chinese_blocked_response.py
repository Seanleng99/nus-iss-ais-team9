import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from coach_i18n import localize_reviewed
from fastapi.testclient import TestClient
from language_fixtures import language_case
from sqlalchemy import event, select
from sqlalchemy.dialects import postgresql, sqlite

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import (
    BLOCKED_AGENT_RATIONALE,
    BLOCKED_AGENT_SUMMARY,
    BLOCKED_EDUCATIONAL_DISCLAIMER,
    BLOCKED_RESPONSE_ANSWER,
    BLOCKED_ROUTING_RATIONALE,
    CoachRequest,
    CoachResponse,
)
from app.infrastructure.database import get_db_session
from app.infrastructure.models import ChatMessageRecord, OrchestrationTraceRecord
from app.jobs.purge_orchestration_traces import purge_expired_traces
from app.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}
USER_ID = "localized-blocked-user"
SESSION_ID = "localized-blocked-chat"
TRACE_IDS: dict[str, str] = {}
CHINESE_REQUEST = language_case("chinese_blocked_response.chinese_request")
POISON = "POISONED_MODEL_PAYLOAD"
PRIVATE_DATA = "POISONED_PRIVATE_DATA"
POISON_SOURCE = {
    "source_id": "poison-source",
    "title": "POISONED_CITATION_TITLE",
    "issuing_organization": "POISONED_CITATION_ORG",
    "canonical_url": "https://poison.example/POISONED_CITATION_URL",
    "published_at": "2026-01-01",
}
SAFE_NOTES = [
    "regulated_advice:tell me exactly what to invest in",
    "email",
    "prompt_injection:3",
    "response_withheld",
]
SAFE_TEXT = {
    "Chinese": {
        "answer": language_case("chinese_blocked_response.safe_text"),
        "summary": language_case("chinese_blocked_response.safe_text_2"),
        "rationale": language_case("chinese_blocked_response.safe_text_3"),
        "routing": language_case("chinese_blocked_response.safe_text_4"),
    },
    "English": {
        "answer": BLOCKED_RESPONSE_ANSWER,
        "summary": BLOCKED_AGENT_SUMMARY,
        "rationale": BLOCKED_AGENT_RATIONALE,
        "routing": BLOCKED_ROUTING_RATIONALE,
    },
}


def _poisoned_agent() -> dict[str, Any]:
    return {
        "agent": "budget",
        "summary": POISON,
        "rationale": [POISON, PRIVATE_DATA],
        "confidence": 0.12,
        "data": {"detail": POISON, "private_data": PRIVATE_DATA},
        "blocked": True,
        "policy_notes": [
            POISON,
            PRIVATE_DATA,
            "regulated_advice:POISONED_NOTE",
            "prompt_injection:12",
            *SAFE_NOTES,
        ],
    }


class LanguageSpoofingBlockedAIServiceClient:
    def __init__(self, claimed_language: Any) -> None:
        self.claimed_language = claimed_language

    async def coach(self, request: CoachRequest) -> CoachResponse:
        # Like the real client, return a validated response, already sanitized once.
        return CoachResponse.model_validate(
            {
                "session_id": request.session_id,
                "selected_agents": ["budget"],
                "answer": POISON,
                "agent_results": [_poisoned_agent()],
                "disclaimers": [POISON, PRIVATE_DATA],
                "sources": [POISON_SOURCE],
                "audit": {
                    "trace_id": f"trace-{request.session_id}",
                    "response_language": self.claimed_language,
                    "routing_rationale": [POISON, PRIVATE_DATA],
                    "model_provider": "fixture",
                    "model_id": "localized-fixture",
                    "prompt_set_version": "v3",
                },
                "blocked": True,
            }
        )


def _post_request(
    monkeypatch: pytest.MonkeyPatch,
    message: str = CHINESE_REQUEST,
    claimed_language: Any = "English",
    session_id: str = SESSION_ID,
    response_locale: str = "zh-Hans",
) -> dict[str, Any]:
    fake = LanguageSpoofingBlockedAIServiceClient(claimed_language)
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: fake)
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": USER_ID, "session_id": session_id, "message": message, "response_locale": response_locale},
    )
    assert response.status_code == 200
    monkeypatch.setitem(TRACE_IDS, session_id, response.json()["audit"]["trace_id"])
    return response.json()


def _expected_agent(language: str) -> dict[str, Any]:
    return {
        "agent": "budget",
        "summary": SAFE_TEXT[language]["summary"],
        "rationale": [SAFE_TEXT[language]["rationale"]],
        "confidence": 1.0,
        "data": {},
        "blocked": True,
        "policy_notes": SAFE_NOTES,
    }


def _assert_surfaces(
    language: str, user_message: str = CHINESE_REQUEST, *, trace_present: bool = True
) -> None:
    history = client.get(
        f"/api/users/{USER_ID}/chat-sessions/{SESSION_ID}", headers=HEADERS
    )
    trace = client.get(
        f"/api/coach/traces/{TRACE_IDS[SESSION_ID]}?user_id={USER_ID}", headers=HEADERS
    )
    exported = client.get(f"/api/users/{USER_ID}/data-export", headers=HEADERS)
    assert history.status_code == exported.status_code == 200
    assert trace.status_code == (200 if trace_present else 404)
    for response in (history, trace, exported):
        assert "POISONED" not in response.text
    messages = history.json()["messages"]
    export_messages = exported.json()["data"]["chat_sessions"][0]["messages"]
    assert messages[1]["id"] == export_messages[1]["id"]
    for items in (messages, export_messages):
        assert items[0]["content"] == user_message
        assert items[1]["content"] == SAFE_TEXT[language]["answer"]
        assert items[1]["sources"] == []
    explanation = messages[1]["explanation"]
    export_trace = export_messages[1]["orchestration_trace"]
    if not trace_present:
        assert explanation is None
        assert export_trace is None
        return
    assert explanation["response_language"] == language
    assert trace.json()["assistant_message_id"] == messages[1]["id"]
    assert explanation["trace_id"] == TRACE_IDS[SESSION_ID]
    assert explanation["routing_rationale"] == [SAFE_TEXT[language]["rationale"]]
    assert explanation["agent_results"] == [
        {
            "agent": "budget",
            "rationale": [SAFE_TEXT[language]["rationale"]],
            "confidence": 1.0,
            "blocked": True,
        }
    ]
    for item in (trace.json(), export_trace):
        assert item["trace_id"] == TRACE_IDS[SESSION_ID]
        assert item["selected_agents"] == ["budget"]
        assert item["agent_results"] == [_expected_agent(language)]
        assert item["audit"]["response_language"] == language
        assert item["audit"]["routing_rationale"] == [SAFE_TEXT[language]["routing"]]
        assert item["prompt_set_version"] == "v3"


@pytest.mark.parametrize(
    ("message", "claimed_language", "expected_language"),
    [
        (CHINESE_REQUEST, "English", "Chinese"),
        (CHINESE_REQUEST, POISON, "Chinese"),
        (CHINESE_REQUEST, {"language": POISON}, "Chinese"),
        (CHINESE_REQUEST, [POISON], "Chinese"),
        (CHINESE_REQUEST, None, "Chinese"),
        ("Create a budget", "Chinese", "English"),
        (
            language_case(
                "chinese_blocked_response.test_request_language_overrides_model_claim_across_all_surfaces"
            ),
            "English",
            "Chinese",
        ),
        (
            language_case(
                "chinese_blocked_response.test_request_language_overrides_model_claim_across_all_surfaces_2"
            ),
            "English",
            "Chinese",
        ),
        (
            language_case(
                "chinese_blocked_response.test_request_language_overrides_model_claim_across_all_surfaces_3"
            ),
            "Chinese",
            "English",
        ),
    ],
)
def test_request_language_overrides_model_claim_across_all_surfaces(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
    claimed_language: Any,
    expected_language: str,
) -> None:
    response = _post_request(monkeypatch, message, claimed_language, response_locale="zh-Hans" if expected_language == "Chinese" else "en")
    safe_text = SAFE_TEXT[expected_language]
    assert "POISONED" not in json.dumps(response)
    assert response["blocked"] is True
    assert response["answer"] == safe_text["answer"]
    assert response["sources"] == []
    assert response["disclaimers"] == [
        localize_reviewed(BLOCKED_EDUCATIONAL_DISCLAIMER, expected_language),
        safe_text["rationale"],
    ]
    assert response["agent_results"] == [_expected_agent(expected_language)]
    assert response["audit"]["response_language"] == expected_language
    assert response["audit"]["routing_rationale"] == [safe_text["routing"]]
    _assert_surfaces(expected_language, message)
    session = next(app.dependency_overrides[get_db_session]())
    try:
        record = session.get(OrchestrationTraceRecord, TRACE_IDS[SESSION_ID])
        assert record is not None
        assert record.audit["response_language"] == expected_language
        assert record.assistant_message.content == safe_text["answer"]
        assert record.assistant_message.sources == []
    finally:
        session.close()


@pytest.mark.parametrize("removal", ["delete", "expiry"])
def test_chinese_poisoned_storage_is_safe_before_and_after_trace_removal(
    monkeypatch: pytest.MonkeyPatch, removal: str
) -> None:
    _post_request(monkeypatch)
    now = datetime.now(UTC)
    session = next(app.dependency_overrides[get_db_session]())
    try:
        record = session.get(OrchestrationTraceRecord, TRACE_IDS[SESSION_ID])
        assert record is not None
        record.agent_results = [_poisoned_agent()]
        record.audit = {**record.audit, "routing_rationale": [POISON, PRIVATE_DATA]}
        record.assistant_message.content = POISON
        record.assistant_message.sources = [POISON_SOURCE]
        record.created_at = now - timedelta(days=31)
        assistant_id = record.assistant_message_id
        session.commit()
    finally:
        session.close()

    _assert_surfaces("Chinese")
    if removal == "delete":
        deleted = client.delete(
            f"/api/coach/traces/{TRACE_IDS[SESSION_ID]}?user_id={USER_ID}", headers=HEADERS
        )
        assert deleted.status_code == 204
    else:
        session = next(app.dependency_overrides[get_db_session]())
        try:
            deleted_count, _ = purge_expired_traces(session, 30, now=now)
            assert deleted_count == 1
        finally:
            session.close()
    _assert_surfaces("Chinese", trace_present=False)
    session = next(app.dependency_overrides[get_db_session]())
    try:
        stored = session.get(ChatMessageRecord, assistant_id)
        assert stored is not None
        assert stored.content == SAFE_TEXT["Chinese"]["answer"]
        assert stored.sources == []
    finally:
        session.close()


@pytest.mark.parametrize("audit_language", [None, "chinese", "Chinese ", POISON, {}, []])
def test_legacy_unknown_language_uses_english_at_read_and_delete_boundaries(
    monkeypatch: pytest.MonkeyPatch, audit_language: Any
) -> None:
    _post_request(monkeypatch)
    session = next(app.dependency_overrides[get_db_session]())
    try:
        record = session.get(OrchestrationTraceRecord, TRACE_IDS[SESSION_ID])
        assert record is not None
        record.audit = {
            "response_language": audit_language,
            "routing_rationale": [POISON],
        }
        record.agent_results = [_poisoned_agent()]
        record.assistant_message.content = POISON
        record.assistant_message.sources = [POISON_SOURCE]
        session.commit()
    finally:
        session.close()
    _assert_surfaces("English")
    deleted = client.delete(
        f"/api/coach/traces/{TRACE_IDS[SESSION_ID]}?user_id={USER_ID}", headers=HEADERS
    )
    assert deleted.status_code == 204
    _assert_surfaces("English", trace_present=False)


def test_bulk_expiry_localizes_exact_chinese_and_defaults_every_other_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = [
        ("chinese", {"response_language": "Chinese"}, "Chinese"),
        ("english", {"response_language": "English"}, "English"),
        ("missing", {}, "English"),
        ("null", {"response_language": None}, "English"),
        ("invalid", {"response_language": POISON}, "English"),
        ("case", {"response_language": "chinese"}, "English"),
        ("object", {"response_language": {"value": "Chinese"}}, "English"),
        ("array", {"response_language": ["Chinese"]}, "English"),
        ("number", {"response_language": 42}, "English"),
    ]
    for name, _, _ in cases:
        _post_request(monkeypatch, session_id=name)
    for name in ("current", "unblocked", "user-role"):
        _post_request(monkeypatch, session_id=name)
    now = datetime.now(UTC)
    statements = []
    session = next(app.dependency_overrides[get_db_session]())
    try:
        for name, audit, _ in cases:
            record = session.get(OrchestrationTraceRecord, TRACE_IDS[name])
            assert record is not None
            record.audit = audit
            record.assistant_message.content = POISON
            record.assistant_message.sources = [POISON_SOURCE]
            record.created_at = now - timedelta(days=31)
        for name in ("current", "unblocked", "user-role"):
            record = session.get(OrchestrationTraceRecord, TRACE_IDS[name])
            assert record is not None
            record.assistant_message.content = f"Untouched {name}"
            record.assistant_message.sources = [POISON_SOURCE]
            if name != "current":
                record.created_at = now - timedelta(days=31)
            if name == "unblocked":
                record.blocked = False
            elif name == "user-role":
                record.assistant_message.role = "user"
        session.commit()

        def capture_statement(state: Any) -> None:
            if state.is_update:
                statements.append(state.statement)

        event.listen(session, "do_orm_execute", capture_statement)
        try:
            deleted_count, _ = purge_expired_traces(session, 30, now=now)
        finally:
            event.remove(session, "do_orm_execute", capture_statement)
        assert deleted_count == len(cases) + 2
        assert len(statements) == 3
        for statement in statements[1:]:
            for dialect in (sqlite.dialect(), postgresql.dialect()):
                compiled = statement.compile(dialect=dialect)
                assert "response_language" in compiled.params.values()
                assert "orchestration_traces" in str(compiled)
        session.expire_all()
        for name, _, language in cases:
            message = session.scalar(
                select(ChatMessageRecord).where(
                    ChatMessageRecord.session_id == name,
                    ChatMessageRecord.role == "assistant",
                )
            )
            assert message is not None
            assert message.content == SAFE_TEXT[language]["answer"]
            assert message.sources == []
            assert session.get(OrchestrationTraceRecord, TRACE_IDS[name]) is None
        for name in ("current", "unblocked", "user-role"):
            message = session.scalar(
                select(ChatMessageRecord).where(
                    ChatMessageRecord.session_id == name, ChatMessageRecord.position == 2
                )
            )
            assert message is not None
            assert message.content == f"Untouched {name}"
            assert message.sources == [POISON_SOURCE]
        assert session.get(OrchestrationTraceRecord, TRACE_IDS["current"]) is not None
    finally:
        session.close()

    exported = client.get(f"/api/users/{USER_ID}/data-export", headers=HEADERS)
    assert exported.status_code == 200
    exports = {item["id"]: item for item in exported.json()["data"]["chat_sessions"]}
    for name, _, language in cases:
        history = client.get(
            f"/api/users/{USER_ID}/chat-sessions/{name}", headers=HEADERS
        )
        assert history.status_code == 200
        assert "POISONED" not in history.text
        for message in (history.json()["messages"][1], exports[name]["messages"][1]):
            assert message["content"] == SAFE_TEXT[language]["answer"]
            assert message["sources"] == []
