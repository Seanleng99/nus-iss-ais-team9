from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.config import settings
from app.infrastructure.models import OrchestrationTraceRecord
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyOrchestrationTraceRepository,
)
from app.main import app

HEADERS = {"X-API-Key": settings.api_key}


def seed(factory):
    now = datetime.now(UTC)
    with factory() as session:
        for owner in ("owner", "other"):
            chat = SQLAlchemyChatRepository(session).create(
                owner, f"chat-{owner}", "Private question"
            )
            for index, status in enumerate(("completed", "failed", "running")):
                record = SQLAlchemyOrchestrationTraceRepository(session).create(
                    trace_id=f"{owner}-{index}",
                    session_id=chat.id,
                    assistant_message_id=None,
                    selected_agents=["budget"],
                    agent_results=[],
                    audit={"private": "DO_NOT_LIST_PAYLOADS"},
                    blocked=False,
                )
                record.status = status
                record.created_at = now - timedelta(minutes=index)
                if status == "running":
                    record.deadline_at = now - timedelta(seconds=1)
        session.commit()


def test_list_is_scoped_paginated_and_reconciles_only_the_owner(db_session_factory):
    seed(db_session_factory)
    client = TestClient(app)
    first = client.get("/api/coach/traces?user_id=owner&limit=2", headers=HEADERS)
    assert first.status_code == 200
    assert [item["trace_id"] for item in first.json()["items"]] == ["owner-0", "owner-1"]
    assert first.json()["next_offset"] == 2
    assert "DO_NOT_LIST_PAYLOADS" not in first.text
    second = client.get("/api/coach/traces?user_id=owner&limit=2&offset=2", headers=HEADERS).json()
    assert second["next_offset"] is None
    assert second["items"][0]["status"] == "abandoned"
    with db_session_factory() as session:
        assert session.get(OrchestrationTraceRecord, "other-2").status == "running"
    filtered = client.get("/api/coach/traces?user_id=owner&status=failed", headers=HEADERS).json()
    assert [item["trace_id"] for item in filtered["items"]] == ["owner-1"]
    assert client.get("/api/coach/traces?user_id=missing", headers=HEADERS).json()["items"] == []


def test_list_requires_authentication_and_valid_filters():
    client = TestClient(app)
    assert client.get("/api/coach/traces?user_id=owner").status_code == 401
    for query in ("limit=101", "limit=0", "offset=-1", "status=invalid"):
        assert (
            client.get(f"/api/coach/traces?user_id=owner&{query}", headers=HEADERS).status_code
            == 422
        )


def test_list_enforces_profile_ownership(db_session_factory):
    from app.core.security import AuthenticatedPrincipal, require_principal
    from app.infrastructure.models import UserRecord

    seed(db_session_factory)
    with db_session_factory() as session:
        user = session.get(UserRecord, "owner")
        user.owner_issuer = "https://issuer.test"
        user.owner_subject = "person-1"
        session.commit()
    principal = AuthenticatedPrincipal(
        authentication_method="oidc", issuer="https://issuer.test", subject="person-1"
    )
    app.dependency_overrides[require_principal] = lambda: principal
    try:
        client = TestClient(app)
        assert client.get("/api/coach/traces?user_id=owner").status_code == 200
        assert client.get("/api/coach/traces?user_id=other").status_code == 404
    finally:
        app.dependency_overrides.pop(require_principal, None)
