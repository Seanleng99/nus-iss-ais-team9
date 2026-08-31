from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infrastructure.database import Base
from app.infrastructure.models import ChatSessionRecord, UserRecord
from app.jobs.purge_data_lifecycle import purge_expired_data


def test_data_lifecycle_retention_is_scoped_and_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    old = now - timedelta(days=100)
    with Session(engine) as session:
        session.add_all(
            [
                UserRecord(id="chat-user", last_activity_at=now),
                UserRecord(id="deployment-expired", last_activity_at=old),
                UserRecord(id="deployment-active", last_activity_at=now),
                UserRecord(id="legacy-unowned", last_activity_at=old),
                UserRecord(
                    id="owned-user",
                    owner_issuer="https://issuer.example",
                    owner_subject="owner",
                    last_activity_at=old,
                ),
            ]
        )
        session.add(
            ChatSessionRecord(
                id="expired-chat",
                user_id="chat-user",
                title="Old conversation",
                created_at=old,
                updated_at=old,
            )
        )
        session.commit()

        first = purge_expired_data(
            session,
            trace_retention_days=30,
            chat_retention_days=90,
            synthetic_user_retention_days=30,
            synthetic_user_prefixes=("deployment-",),
            now=now,
        )
        second = purge_expired_data(
            session,
            trace_retention_days=30,
            chat_retention_days=90,
            synthetic_user_retention_days=30,
            synthetic_user_prefixes=("deployment-",),
            now=now,
        )
        remaining_users = set(session.scalars(select(UserRecord.id)))
        remaining_chats = list(session.scalars(select(ChatSessionRecord.id)))

    assert first["policy_version"] == "data-lifecycle-v1"
    assert first["deleted_counts"] == {
        "orchestration_traces": 0,
        "chat_sessions": 1,
        "synthetic_automation_users": 1,
    }
    assert second["deleted_counts"] == {
        "orchestration_traces": 0,
        "chat_sessions": 0,
        "synthetic_automation_users": 0,
    }
    assert remaining_users == {
        "chat-user",
        "deployment-active",
        "legacy-unowned",
        "owned-user",
    }
    assert remaining_chats == []
    engine.dispose()
