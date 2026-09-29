import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import SQLAlchemyTransactionRepository
from app.services.transaction_capture import extract_date_from_text, mentions_future_date

SPENDING_INTENT_PATTERN = re.compile(
    r"\b(?:spend\w*|spent|expense\w*)\b", re.IGNORECASE
)


def parse_date_spending_query(message: str) -> date | None:
    text = message.strip()
    if not SPENDING_INTENT_PATTERN.search(text):
        return None
    if re.search(r"\b(?:budget|budgeting|afford)\b", text, re.IGNORECASE):
        return None
    if mentions_future_date(text):
        return None
    return extract_date_from_text(text)


def _formatted_date(when: date) -> str:
    return f"{when.strftime('%A, %d %B %Y')}".replace(" 0", " ")


def _reply(session_id: str, answer: str) -> CoachResponse:
    audit: dict[str, Any] = {"source": "spending_date_query"}
    return CoachResponse(
        session_id=session_id,
        selected_agents=[],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit=audit,
    )


def handle_date_spending_query(
    session: Session, request: CoachRequest, when: date
) -> CoachResponse:
    month_start = when.replace(day=1)
    records = SQLAlchemyTransactionRepository(session).list_records(
        request.user_id, period_start=month_start
    )
    records = [record for record in records if record.transaction_type == "expense"]
    day_records = [record for record in records if record.occurred_on == when]
    label = _formatted_date(when)
    if not day_records:
        return _reply(
            request.session_id,
            f"You have no transactions on {label}. Would you like to log one? "
            "For example: 'I have spent $5 on chicken rice today'.",
        )
    total = sum(float(record.amount) for record in day_records)
    lines = ", ".join(
        f"{record.description} ({record.category.capitalize()}) SGD {float(record.amount):.2f}"
        for record in day_records
    )
    answer = (
        f"On {label} you had {len(day_records)} transaction"
        f"{'s' if len(day_records) != 1 else ''}: {lines}. "
        f"Total: SGD {total:.2f}."
    )
    return _reply(request.session_id, answer)
