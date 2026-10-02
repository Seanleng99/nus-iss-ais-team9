"""Backend-owned spending capture and queries.

Models may propose transaction drafts; only this authenticated backend path
writes transactions. A complete record saves immediately in the same turn (no
pre-save confirmation); only missing fields are clarified. Named edits and
deletions keep their own confirmation path in ``transaction_capture``.
"""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from coach_i18n import input_pattern
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.financial_schemas import TransactionCreate
from app.core.telemetry import log_event
from app.domain.schemas import ApplicationMoneyAmount, CoachRequest, CoachResponse
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
)
from app.services import transaction_capture as capture
from app.services.transaction_capture import (
    LastSavedRecord,
    classify_category,
    extract_date_from_text,
    last_saved_store,
    mentions_future_date,
    parse_date_expression,
)

CANCEL = re.compile(
    input_pattern("backend.services.transaction_staging.cancel"),
    re.IGNORECASE,
)
CONFIRM_OR_CANCEL = re.compile(
    input_pattern("backend.services.transaction_staging.confirm_or_cancel"),
    re.IGNORECASE,
)


class TransactionDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=255)
    amount: float | None = Field(
        default=None, gt=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    category: str | None = Field(default=None, max_length=64)
    occurred_on: date | None = None
    recurring: bool = False
    booking: bool = False


class SpendingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_spending_request: bool = True
    action: Literal["record", "query"] = "record"
    transactions: list[TransactionDraftItem] = Field(default_factory=list, max_length=20)
    query_date: date | None = None
    questions: list[str] = Field(default_factory=list, max_length=8)


def _query_date(draft: SpendingDraft, message: str) -> date | None:
    # Lookups may name booked future days, so future dates resolve for queries.
    return draft.query_date or extract_date_from_text(message, allow_future=True)


PERIOD_PATTERN = re.compile(r"\b(this|last)\s+(month|week|year)\b", re.IGNORECASE)


def _resolve_period(message: str, today: date) -> tuple[date, date, str] | None:
    match = PERIOD_PATTERN.search(message)
    if match is None:
        return None
    which, unit = match.group(1).lower(), match.group(2).lower()
    if unit == "month":
        start = today.replace(day=1)
        if which == "last":
            start = (start - timedelta(days=1)).replace(day=1)
        if start.month == 12:
            end = date(start.year, 12, 31)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        return start, end, f"{start:%B %Y}"
    if unit == "week":
        monday = today - timedelta(days=today.weekday())
        if which == "last":
            monday -= timedelta(days=7)
        return monday, monday + timedelta(days=6), f"the week of {monday:%d %b}"
    year = today.year - 1 if which == "last" else today.year
    return date(year, 1, 1), date(year, 12, 31), str(year)


def _query_resolved(draft: SpendingDraft, message: str) -> bool:
    return (
        _query_date(draft, message) is not None
        or _resolve_period(message, capture._today()) is not None
    )


def _answer_query(session: Session, user_id: str, draft: SpendingDraft, message: str) -> str:
    # A query is answered from owned records; the model never supplies numbers.
    when = _query_date(draft, message)
    if when is None:
        period = _resolve_period(message, capture._today())
        if period is None:
            return (
                "Which day should I look up? Say for example 'on 21/9' or 'yesterday'. "
                "Nothing was saved."
            )
        start, end, label = period
        records = SQLAlchemyTransactionRepository(session).list_records(
            user_id, period_start=start
        )
        period_records = [
            record
            for record in records
            if start <= record.occurred_on <= end and record.transaction_type == "expense"
        ]
        if not period_records:
            return (
                f"You have no transactions in {label}. Would you like to log one? "
                "For example: 'I have spent $5 on chicken rice today'."
            )
        total = sum(float(record.amount) for record in period_records)
        lines = ", ".join(
            f"{record.description} ({record.category.capitalize()}) "
            f"SGD {float(record.amount):.2f}"
            for record in period_records
        )
        return (
            f"In {label} you had {len(period_records)} transaction"
            f"{'s' if len(period_records) != 1 else ''}: {lines}. "
            f"Total: SGD {total:.2f}."
        )
    records = SQLAlchemyTransactionRepository(session).list_records(
        user_id, period_start=when.replace(day=1)
    )
    day_records = [
        record
        for record in records
        if record.occurred_on == when and record.transaction_type == "expense"
    ]
    label = f"{when.strftime('%A, %d %B %Y')}".replace(" 0", " ")
    if not day_records:
        return (
            f"You have no transactions on {label}. Would you like to log one? "
            "For example: 'I have spent $5 on chicken rice today'."
        )
    total = sum(float(record.amount) for record in day_records)
    lines = ", ".join(
        f"{record.description} ({record.category.capitalize()}) "
        f"SGD {float(record.amount):.2f}"
        for record in day_records
    )
    return (
        f"On {label} you had {len(day_records)} transaction"
        f"{'s' if len(day_records) != 1 else ''}: {lines}. "
        f"Total: SGD {total:.2f}."
    )


def _save_dated(
    session: Session, user_id: str, dated: list[tuple[TransactionDraftItem, date]]
) -> tuple[CoachResponse | None, str]:
    saved_parts: list[str] = []
    for item, when in dated:
        category = " ".join((item.category or "").split()).lower() or classify_category(
            item.description or ""
        )
        try:
            record = SQLAlchemyTransactionRepository(session).create(
                user_id,
                TransactionCreate(
                    description=item.description,
                    category=category,
                    amount=ApplicationMoneyAmount(amount=item.amount),
                    occurred_on=when,
                    recurring=item.recurring,
                ),
            )
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            return (
                CoachResponse(
                    session_id="",
                    selected_agents=["spending"],
                    answer="Sorry, I couldn't save that transaction. Please try again.",
                    agent_results=[],
                    disclaimers=[],
                    audit={"source": "spending_capture"},
                ),
                "",
            )
        except ValueError:
            session.rollback()
            return (
                CoachResponse(
                    session_id="",
                    selected_agents=["spending"],
                    answer=(
                        "Please provide the description, category and SGD amount again. "
                        "Nothing was saved."
                    ),
                    agent_results=[],
                    disclaimers=[],
                    audit={"source": "spending_capture"},
                ),
                "",
            )
        last_saved_store.remember(
            user_id,
            LastSavedRecord(
                transaction_id=record.id,
                description=item.description,
                category=category,
                amount=item.amount,
                when=when,
                recurring=item.recurring,
            ),
        )
        log_event("transaction.added", source="coach_capture", category=category)
        saved_parts.append(
            f"{item.description} for SGD {item.amount:.2f} on {when.day} "
            f"{when.strftime('%b %Y')} under {category.capitalize()}"
        )
    from app.services.budget_alert import category_overage_note

    flagged: list[str] = []
    for (item, when), part in zip(dated, saved_parts, strict=True):
        category = " ".join((item.category or "").split()).lower() or classify_category(
            item.description or ""
        )
        note = category_overage_note(session, user_id, when.replace(day=1), category)
        flagged.append(part + (" " + note.strip() if note else ""))
    body = "; ".join(flagged)
    answer = f"Saved: {body}" + ("" if body.endswith((".", "!")) else ".")
    return None, answer


def _message_segments(message: str) -> list[str]:
    raw = re.split(r"[\r\n]+|(?<=:)\s+", message)
    segments: list[str] = []
    for line in raw:
        segments.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", line) if part.strip())
    return segments


def _item_date(item: TransactionDraftItem, message: str, segments: list[str]) -> date | None:
    if item.occurred_on is not None:
        return item.occurred_on
    # A bare date reply ("yesterday", "21/9") answers the pending draft as a whole.
    bare = parse_date_expression(message, allow_future=item.booking)
    if bare is not None:
        return bare
    words = {
        word
        for word in re.sub(r"[^a-z0-9 ]", " ", (item.description or "").lower()).split()
    }
    header_date: date | None = None
    for segment in segments:
        found = extract_date_from_text(segment, allow_future=item.booking)
        if found is None:
            continue
        segment_words = set(re.sub(r"[^a-z0-9 ]", " ", segment.lower()).split())
        if words & segment_words:
            return found
        # A date written before any amount ("yesterday i spent ...") heads the
        # whole line; a date trailing one item ("... mrt yesterday") must not
        # leak to sibling items.
        first_digit = re.search(r"\d", segment)
        date_match = re.search(
            r"\b(today|yesterday|\d{1,2}/\d{1,2}|\d{1,2}(?:st|nd|rd|th)?\s+\w+|\w+\s+\d{1,2})\b",
            segment.lower(),
        )
        leads_line = (
            date_match is not None
            and (first_digit is None or date_match.start() < first_digit.start())
        )
        if header_date is None and leads_line:
            header_date = found
    return header_date


def _resolve_record(
    session: Session, user_id: str, draft: SpendingDraft, message: str
) -> tuple[str, list[TransactionDraftItem]]:
    """Validate draft items, saving the complete ones immediately.

    Returns ``(extra_answer, incomplete)`` where ``extra_answer`` is the
    "Saved: ..." text for the items already written (empty when none) and
    ``incomplete`` lists the items still missing fields (dates already merged
    from this message). An empty incomplete list with no saved text means the
    draft held no usable items at all.
    """
    if not draft.transactions:
        return (
            (
                "Tell me what you spent and how much, for example "
                "'I spent $5 on chicken rice today'. Nothing was saved."
            ),
            [],
        )
    today = capture._today()
    segments = _message_segments(message)
    questions: list[str] = []
    dated: list[tuple[TransactionDraftItem, date]] = []
    incomplete: list[TransactionDraftItem] = []
    for index, item in enumerate(draft.transactions, 1):
        label = (item.description or f"item {index}").strip()
        problems: list[str] = []
        if not (item.description or "").strip():
            problems.append("What did you spend the money on?")
        if item.amount is None:
            problems.append(
                f"How much did the {label} cost? You can say for example 'about 25' or '$25'."
            )
        when = _item_date(item, message, segments)
        if when is not None and when > today and not item.booking:
            problems.append(
                f"The {label} is dated {when:%d %b %Y}, which is in the future. "
                "When did you spend it?"
            )
            when = None
        if when is None:
            if (item.description or "").strip():
                if mentions_future_date(message) and not item.booking:
                    problems.append(
                        f"That date for the {label} is in the future — when did you spend it?"
                    )
                else:
                    problems.append(
                        f"When did you spend the {label}? "
                        "You can say 'yesterday', 'today', or a date like 21/9."
                    )
            item.occurred_on = None
        else:
            item.occurred_on = when
        if problems:
            incomplete.append(item)
            questions.extend(problems)
            continue
        dated.append((item, when))
    questions = list(dict.fromkeys(questions))
    saved_answer = ""
    if dated:
        error, saved_answer = _save_dated(session, user_id, dated)
        if error is not None:
            # A failed write keeps the whole record draft pending for a retry.
            return error.answer, list(draft.transactions)
    if questions:
        extra = "Nothing has been saved. " + " ".join(questions)
        if saved_answer:
            extra = saved_answer + " " + extra.replace("Nothing has been saved. ", "")
        return extra, incomplete
    return saved_answer, []


def stage_transaction_draft(
    session: Session, user_id: str, chat, response: CoachResponse, message: str
) -> None:
    if chat.pending_transaction:
        chat.pending_transaction = {**chat.pending_transaction, "ready": False}
    if response.blocked:
        return
    result = next(
        (
            item
            for item in response.agent_results
            if item.agent.value == "spending" and not item.blocked and "spending_draft" in item.data
        ),
        None,
    )
    if result is None:
        # No spending extraction this turn: the conversation moved on, so an
        # unfinished record draft is dropped rather than silently saved later.
        chat.pending_transaction = None
        return
    try:
        draft = SpendingDraft.model_validate(result.data["spending_draft"])
    except ValidationError:
        response.answer = (
            "Nothing has been saved. Please provide what you spent, the SGD amount and the date again."
        )
        response.audit["spending_capture"] = "invalid_draft"
        return
    if not draft.is_spending_request:
        # A non-spending message abandons any unfinished record draft so a later
        # bare reply cannot silently save stale spending.
        chat.pending_transaction = None
        return
    if draft.action == "query":
        response.answer = _answer_query(session, user_id, draft, message)
        # A resolved lookup clears any older record draft; an unresolved lookup
        # stays pending so a follow-up date (e.g. "3rd Oct") can complete it.
        if _query_resolved(draft, message):
            chat.pending_transaction = None
            response.audit["spending_capture"] = "read_only_query"
        else:
            chat.pending_transaction = _pending(draft)
            response.audit["spending_capture"] = "needs_input"
        return
    leftover = _merge_pending(chat, draft)
    answer, incomplete = _resolve_record(session, user_id, leftover, message)
    response.answer = answer
    if incomplete:
        chat.pending_transaction = _pending(leftover.model_copy(update={"transactions": incomplete}))
        response.audit["spending_capture"] = "needs_input"
    else:
        chat.pending_transaction = None
        response.audit["spending_capture"] = "saved"


def _pending(draft: SpendingDraft) -> dict:
    return {
        "draft": draft.model_dump(mode="json"),
        "baseline": None,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }


def _merge_pending(chat, draft: SpendingDraft) -> SpendingDraft:
    # A follow-up answer (an amount or a date) continues the unfinished draft:
    # its items are merged in place instead of starting a brand new record.
    pending = chat.pending_transaction
    if not pending or draft.transactions:
        return draft
    try:
        stored = SpendingDraft.model_validate(pending["draft"])
    except (ValidationError, KeyError, TypeError):
        return draft
    if stored.action != "record":
        return draft
    return stored


def handle_transaction_confirmation(
    session: Session, request: CoachRequest
) -> CoachResponse | None:
    text = request.message.strip()
    if not CONFIRM_OR_CANCEL.fullmatch(text):
        return None
    chat = SQLAlchemyChatRepository(session).get_for_update(request.user_id, request.session_id)
    if chat is None or not chat.pending_transaction:
        # Never intercept confirm/cancel words meant for budget or goal drafts.
        return None
    if CANCEL.fullmatch(text):
        chat.pending_transaction = None
        answer = "Transaction cancelled. Nothing was saved."
    else:
        chat.pending_transaction = None
        answer = (
            "There is nothing waiting to save. Tell me what you spent and how much, "
            "for example 'I spent $5 on chicken rice today'."
        )
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=["spending"],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit={"source": "spending_capture"},
    )
