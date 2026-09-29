"""Owned planning preferences shared by cash-flow, allocation and continuity tools."""

from app.infrastructure.models import PlanningPreferencesRecord
from app.infrastructure.repositories import _ensure_user, _touch_user


def read_section(session, user_id, section):
    record = session.get(PlanningPreferencesRecord, user_id)
    return (record.data or {}).get(section) if record else None


def write_section(session, user_id, section, value):
    _ensure_user(session, user_id)
    record = session.get(PlanningPreferencesRecord, user_id)
    if record is None:
        record = PlanningPreferencesRecord(user_id=user_id, data={})
        session.add(record)
    record.data = {**record.data, section: value}
    _touch_user(session, user_id)
    session.flush()
    return value
