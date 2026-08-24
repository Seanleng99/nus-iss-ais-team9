import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.infrastructure.database import SessionLocal
from app.infrastructure.repositories import SQLAlchemyOrchestrationTraceRepository


def purge_expired_traces(
    session: Session,
    retention_days: int,
    *,
    now: datetime | None = None,
) -> tuple[int, datetime]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    deleted_count = SQLAlchemyOrchestrationTraceRepository(session).delete_expired(cutoff)
    session.commit()
    return deleted_count, cutoff


def main() -> None:
    with SessionLocal() as session:
        deleted_count, cutoff = purge_expired_traces(
            session,
            settings.trace_retention_days,
        )
    print(
        json.dumps(
            {
                "event": "orchestration_trace_retention_completed",
                "retention_days": settings.trace_retention_days,
                "cutoff": cutoff.isoformat(),
                "deleted_count": deleted_count,
            }
        )
    )


if __name__ == "__main__":
    main()
