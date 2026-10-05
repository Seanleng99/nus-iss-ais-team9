"""Conversation-owned durable action references, consumed with the chat lock."""

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.infrastructure.models import CoachActionStateRecord
from app.infrastructure.repositories import SQLAlchemyChatRepository


class DurableActionStore:
    def __init__(self, session, user_id, session_id, locale="en"):
        self.session = session
        self.user_id = user_id
        self.session_id = session_id
        self.locale = locale

    def _row(self, create=False):
        repository = SQLAlchemyChatRepository(self.session)
        chat = repository.get_for_update(self.user_id, self.session_id)
        if chat is None:
            if not create:
                return None
            if repository.id_exists(self.session_id):
                raise PermissionError("Conversation not found")
            repository.create(self.user_id, self.session_id, "Coach")
        row = self.session.scalar(select(CoachActionStateRecord).where(
            CoachActionStateRecord.session_id == self.session_id,
            CoachActionStateRecord.user_id == self.user_id,
        ).with_for_update())
        if row is None and create:
            row = CoachActionStateRecord(user_id=self.user_id, session_id=self.session_id)
            self.session.add(row)
            self.session.flush()
        return row

    def read(self, field):
        row = self._row()
        payload = getattr(row, field) if row is not None else None
        if payload is None:
            return None
        if datetime.fromisoformat(payload["expires_at"]) <= datetime.now(UTC):
            setattr(row, field, None)
            return None
        return payload["value"]

    def write(self, field, value):
        row = self._row(create=value is not None)
        if row is not None:
            setattr(row, field, None if value is None else {
                "value": value,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
            })


def _encode(record):
    return {key: str(value) if isinstance(value, (UUID, date)) else value
            for key, value in asdict(record).items()}


def _decode(value, record_type):
    return record_type(**{**value, "transaction_id": UUID(value["transaction_id"]),
                          "when": date.fromisoformat(value["when"])})


class DurableLastSavedStore(DurableActionStore):
    def remember(self, user_id, record):
        assert user_id == self.user_id
        self.write("last_saved", _encode(record))

    def get(self, user_id):
        assert user_id == self.user_id
        from app.services.transaction_capture import LastSavedRecord
        value = self.read("last_saved")
        return _decode(value, LastSavedRecord) if value is not None else None

    def clear(self):
        self.write("last_saved", None)


class DurablePendingEditStore(DurableActionStore):
    def put(self, user_id, pending):
        assert user_id == self.user_id
        self.write("pending_edit", {
            "new_amount": pending.new_amount, "op": pending.op,
            "candidates": [_encode(candidate) for candidate in pending.candidates],
            "candidate": _encode(pending.candidate) if pending.candidate is not None else None,
        })

    def get(self, user_id):
        assert user_id == self.user_id
        from app.services.transaction_capture import EditCandidate, PendingEdit
        value = self.read("pending_edit")
        if value is None:
            return None
        return PendingEdit(new_amount=value["new_amount"], op=value["op"],
            candidates=[_decode(candidate, EditCandidate) for candidate in value["candidates"]],
            candidate=_decode(value["candidate"], EditCandidate) if value["candidate"] else None)

    def drop(self, user_id):
        assert user_id == self.user_id
        self.write("pending_edit", None)
