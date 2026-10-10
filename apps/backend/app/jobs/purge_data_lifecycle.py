import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.data_lifecycle import DATA_LIFECYCLE_POLICY_VERSION
from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories import (
    SQLAlchemyDataLifecycleRepository,
    SQLAlchemyOrchestrationTraceRepository,
)
from app.services.coach_quota import purge_quota_records


def purge_expired_data(
    session: Session,
    *,
    trace_retention_days: int,
    chat_retention_days: int,
    synthetic_user_retention_days: int,
    synthetic_user_prefixes: tuple[str, ...],
    now: datetime | None = None,
) -> dict[str, Any]:
    evaluated_at = now or datetime.now(UTC)
    trace_cutoff = evaluated_at - timedelta(days=trace_retention_days)
    chat_cutoff = evaluated_at - timedelta(days=chat_retention_days)
    synthetic_user_cutoff = evaluated_at - timedelta(
        days=synthetic_user_retention_days
    )
    trace_count = SQLAlchemyOrchestrationTraceRepository(session).delete_expired(
        trace_cutoff
    )
    repository = SQLAlchemyDataLifecycleRepository(session)
    chat_count = repository.delete_expired_chat_sessions(chat_cutoff)
    synthetic_user_count = repository.delete_expired_synthetic_users(
        synthetic_user_cutoff, synthetic_user_prefixes
    )
    purge_quota_records(session, evaluated_at)
    session.commit()
    return {
        "event": "data_lifecycle_retention_completed",
        "policy_version": DATA_LIFECYCLE_POLICY_VERSION,
        "evaluated_at": evaluated_at.isoformat(),
        "cutoffs": {
            "orchestration_traces": trace_cutoff.isoformat(),
            "chat_history": chat_cutoff.isoformat(),
            "synthetic_automation_users": synthetic_user_cutoff.isoformat(),
        },
        "deleted_counts": {
            "orchestration_traces": trace_count,
            "chat_sessions": chat_count,
            "synthetic_automation_users": synthetic_user_count,
        },
    }


def main() -> None:
    with SessionLocal() as session:
        result = purge_expired_data(
            session,
            trace_retention_days=settings.trace_retention_days,
            chat_retention_days=settings.chat_retention_days,
            synthetic_user_retention_days=settings.synthetic_user_retention_days,
            synthetic_user_prefixes=settings.automation_user_id_prefix_list,
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
