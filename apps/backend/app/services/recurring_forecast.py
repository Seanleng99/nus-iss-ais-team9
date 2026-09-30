import re
from typing import Any

from sqlalchemy.orm import Session

from app.domain.schemas import CoachResponse
from app.infrastructure.repositories import SQLAlchemyTransactionRepository

FORECAST_INTENT_PATTERN = re.compile(
    r"\b(?:estimate|forecast|project(?:ion|ions)?|predict|expect)\b[^?]*\b"
    r"(?:spendings?|expenses?|costs?|bills?|outgoings?)\b"
    r"|\b(?:recurring|monthly)\b[^?]*\b(?:spendings?|expenses?|costs?|bills?|total)\b"
    r"|\b(?:spendings?|expenses?|costs?|bills?)\b[^?]*\b(?:recurring|per month|monthly total)\b",
    re.IGNORECASE,
)

EDUCATION_PATTERN = re.compile(
    r"\b(?:what is|what are|what's|explain|define|meaning of|difference between)\b",
    re.IGNORECASE,
)
POSSESSIVE_PATTERN = re.compile(r"\b(?:my|mine|our|i|me)\b", re.IGNORECASE)


def parse_recurring_forecast_query(message: str) -> bool:
    text = message.strip()
    if not FORECAST_INTENT_PATTERN.search(text):
        return False
    return not (EDUCATION_PATTERN.search(text) and not POSSESSIVE_PATTERN.search(text))


def _formatted(record) -> str:
    return f"{record.description} SGD {float(record.amount):.2f}"


NOISE_TOKENS = frozenset(
    {"the", "a", "an", "my", "bill", "subscription", "plan", "monthly", "payment", "fee"}
)


def _is_same_item(shorter: str, longer: str) -> bool:
    short_words = [word for word in re.split(r"[^a-z0-9]+", shorter.lower()) if word]
    long_words = [word for word in re.split(r"[^a-z0-9]+", longer.lower()) if word]
    if not short_words:
        return False
    short_key = tuple(word for word in short_words if word not in NOISE_TOKENS)
    long_key = tuple(word for word in long_words if word not in NOISE_TOKENS)
    if short_key == long_key:
        return True
    return bool(short_key) and long_key[: len(short_key)] == short_key


def _latest_recurring(records) -> list:
    dated: dict[tuple[str, str], Any] = {}
    for record in records:
        if not record.recurring:
            continue
        key = (record.description.strip().lower(), record.category)
        current = dated.get(key)
        if current is None or record.occurred_on > current.occurred_on:
            dated[key] = record
    merged: dict[str, list[Any]] = {}
    for record in dated.values():
        bucket = merged.setdefault(record.category, [])
        for existing in bucket:
            a, b = sorted(
                (existing.description.strip().lower(), record.description.strip().lower()),
                key=len,
            )
            if _is_same_item(a, b):
                if record.occurred_on > existing.occurred_on:
                    bucket[bucket.index(existing)] = record
                break
        else:
            bucket.append(record)
    return [record for bucket in merged.values() for record in bucket]


def handle_recurring_forecast_query(
    session: Session, user_id: str, session_id: str
) -> CoachResponse:
    records = SQLAlchemyTransactionRepository(session).list_records(user_id)
    latest = _latest_recurring(records)
    audit: dict[str, Any] = {"source": "recurring_forecast"}

    def reply(answer: str) -> CoachResponse:
        return CoachResponse(
            session_id=session_id,
            selected_agents=[],
            answer=answer,
            agent_results=[],
            disclaimers=[],
            audit=audit,
        )

    if not latest:
        return reply(
            "You haven't recorded any recurring transactions yet, so I can't estimate "
            "your upcoming spending. When you log an expense you pay regularly, mark it "
            "as recurring, for example rent or a subscription, and I can total it here."
        )
    items = sorted(latest, key=lambda r: (-float(r.amount), r.description))
    total = sum(float(r.amount) for r in items)
    if len(items) == 1:
        detail = _formatted(items[0])
    else:
        detail = ", ".join(_formatted(r) for r in items[:-1]) + f", and {_formatted(items[-1])}"
    return reply(
        f"Based on your recurring transactions, your estimated upcoming spending is "
        f"SGD {total:.2f} per month: {detail}. These are your latest recorded recurring "
        f"amounts, not predictions."
    )
