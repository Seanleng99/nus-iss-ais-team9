import re
from datetime import date
from typing import Any

from coach_i18n import request_locale
from sqlalchemy.orm import Session

from app.domain.schemas import CoachRequest, CoachResponse
from app.services.transaction_capture import extract_date_from_text
from app.services.transaction_staging import SpendingDraft, _answer_query

SPENDING_INTENT_PATTERN = re.compile(
    r"\b(?:spend\w*|spent|expense\w*)\b", re.IGNORECASE
)

LISTING_INTENT_PATTERN = re.compile(
    r"\b(?:show|list|display|print|see|what|which)\b[^?.!]*"
    r"\b(?:transaction\w*|purchase\w*|entries|records|items|receipts)\b",
    re.IGNORECASE,
)


def parse_date_spending_query(message: str, session_context: dict | None = None) -> date | None:
    text = message.strip()
    contextual_follow_up = (
        (session_context or {}).get("active_topic") == "spending"
        and re.fullmatch(r"(?:what|how) about .+[?!.]*", text, re.IGNORECASE)
    )
    if not (SPENDING_INTENT_PATTERN.search(text) or LISTING_INTENT_PATTERN.search(text) or contextual_follow_up):
        return None
    if re.search(r"\b(?:budget|budgeting|afford)\b", text, re.IGNORECASE):
        return None
    return extract_date_from_text(text, allow_future=True)


def _formatted_date(when: date) -> str:
    return f"{when.strftime('%A, %d %B %Y')}".replace(" 0", " ")


def _reply(session_id: str, answer: str) -> CoachResponse:
    audit: dict[str, Any] = {"source": "spending_date_query"}
    return CoachResponse(
        session_id=session_id,
        selected_agents=["spending"],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit=audit,
    )


def handle_date_spending_query(
    session: Session, request: CoachRequest, when: date
) -> CoachResponse:
    # Compatibility entry point; typed semantic extraction resolves filters.
    return _reply(request.session_id, _answer_query(
        session, request.user_id, SpendingDraft(action="query", query_date=when),
        request.message, request_locale(request),
    ))
