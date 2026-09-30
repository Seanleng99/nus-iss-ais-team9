"""Owned planning preferences shared by cash-flow, allocation and continuity tools."""

from sqlalchemy import select

from app.infrastructure.models import PlanningPreferencesRecord
from app.infrastructure.repositories import _ensure_user, _lock_user_lifecycle, _touch_user


def read_section(session, user_id, section):
    record = session.get(PlanningPreferencesRecord, user_id)
    return (record.data or {}).get(section) if record else None


def write_section(session, user_id, section, value):
    lock_workspace(session, user_id)
    record = session.get(PlanningPreferencesRecord, user_id)
    if record is None:
        record = PlanningPreferencesRecord(user_id=user_id, data={})
        session.add(record)
    record.data = {**record.data, section: value}
    _touch_user(session, user_id)
    session.flush()
    return value


def lock_workspace(session, user_id):
    _ensure_user(session, user_id)
    _lock_user_lifecycle(session, user_id)
    session.scalar(select(PlanningPreferencesRecord).where(
        PlanningPreferencesRecord.user_id == user_id
    ).with_for_update().execution_options(populate_existing=True))
