from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.domain.schemas import BLOCKED_RESPONSE_ANSWER
from app.infrastructure.database import Base
from app.infrastructure.models import (
    ChatMessageRecord,
    ChatSessionRecord,
    OrchestrationTraceRecord,
    UserRecord,
)
from app.jobs.purge_orchestration_traces import purge_expired_traces


def test_trace_retention_removes_only_expired_records() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(UserRecord(id="retention-user"))
        session.add(
            ChatSessionRecord(
                id="retention-session",
                user_id="retention-user",
                title="Retention test",
            )
        )
        old_message = ChatMessageRecord(
            id=uuid4(),
            session_id="retention-session",
            role="assistant",
            content="Old response",
            position=1,
        )
        current_message = ChatMessageRecord(
            id=uuid4(),
            session_id="retention-session",
            role="assistant",
            content="Current response",
            position=2,
        )
        session.add_all([old_message, current_message])
        session.flush()
        session.add_all(
            [
                OrchestrationTraceRecord(
                    trace_id="expired-trace",
                    session_id="retention-session",
                    assistant_message_id=old_message.id,
                    selected_agents=[],
                    agent_results=[],
                    audit={},
                    blocked=False,
                    created_at=now - timedelta(days=31),
                ),
                OrchestrationTraceRecord(
                    trace_id="current-trace",
                    session_id="retention-session",
                    assistant_message_id=current_message.id,
                    selected_agents=[],
                    agent_results=[],
                    audit={},
                    blocked=False,
                    created_at=now - timedelta(days=29),
                ),
            ]
        )
        session.commit()

        deleted_count, cutoff = purge_expired_traces(session, 30, now=now)
        remaining = session.scalars(select(OrchestrationTraceRecord.trace_id)).all()

    assert cutoff == now - timedelta(days=30)
    assert deleted_count == 1
    assert remaining == ["current-trace"]
    engine.dispose()


def test_trace_retention_sanitizes_expired_blocked_assistant_before_deleting_trace() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(UserRecord(id="blocked-retention-user"))
        session.add(
            ChatSessionRecord(
                id="blocked-retention-session",
                user_id="blocked-retention-user",
                title="Blocked retention test",
            )
        )
        message = ChatMessageRecord(
            id=uuid4(),
            session_id="blocked-retention-session",
            role="assistant",
            content="POISONED_LEGACY_RESPONSE",
            sources=[{"title": "POISONED_SOURCE"}],
            position=1,
        )
        session.add(message)
        session.flush()
        session.add(
            OrchestrationTraceRecord(
                trace_id="expired-blocked-trace",
                session_id="blocked-retention-session",
                assistant_message_id=message.id,
                selected_agents=["budget"],
                agent_results=[],
                audit={},
                blocked=True,
                created_at=now - timedelta(days=31),
            )
        )
        session.commit()

        deleted_count, _ = purge_expired_traces(session, 30, now=now)
        stored_message = session.get(ChatMessageRecord, message.id)
        remaining = session.get(OrchestrationTraceRecord, "expired-blocked-trace")

    assert deleted_count == 1
    assert stored_message is not None
    assert stored_message.content == BLOCKED_RESPONSE_ANSWER
    assert stored_message.sources == []
    assert remaining is None
    engine.dispose()
