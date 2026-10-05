"""Backend-owned spending capture and queries.

Models may propose transaction drafts; only this authenticated backend path
writes transactions. A complete ordinary record saves immediately unless its
typed intent requests a preview. Supplied schedules also require confirmation.
Missing fields are clarified before saving or previewing. Named edits and
deletions keep their own confirmation path in ``transaction_capture``.
"""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from coach_i18n import input_pattern, translate
from coach_math.recurrence import next_occurrence
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.financial_schemas import TransactionCreate
from app.core.telemetry import log_event
from app.domain.recurrence import LedgerRecurrence, RecurrenceTerms
from app.domain.schemas import ApplicationMoneyAmount, CoachRequest, CoachResponse
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
    next_month,
)
from app.services import transaction_capture as capture
from app.services.coach_action_state import DurableLastSavedStore
from app.services.transaction_capture import (
    LastSavedRecord,
    classify_category,
    extract_date_from_text,
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
PREVIEW_CONFIRM = re.compile(
    input_pattern("backend.services.transaction_staging.preview_confirm"), re.IGNORECASE,
)


class DraftRecurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["once", "weekly", "fortnightly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=120, strict=True)
    month_end: bool = False
    first_on: date | None = None
    next_due_on: date | None = None
    last_on: date | None = None


class TransactionDraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=255)
    amount: float | None = Field(
        default=None, gt=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    category: str | None = Field(default=None, max_length=64)
    occurred_on: date | None = None
    recurring: bool = False
    recurrence: DraftRecurrence | None = None
    booking: bool = False


class SpendingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_spending_request: bool = True
    action: Literal["record", "query", "forecast"] = "record"
    persistence_intent: Literal["save", "preview"] = "save"
    transactions: list[TransactionDraftItem] = Field(default_factory=list, max_length=20)
    query_date: date | None = None
    query_start: date | None = None
    query_end: date | None = None
    query_categories: list[str] = Field(default_factory=list, max_length=20)
    query_description: str | None = Field(default=None, max_length=255)
    query_min_amount: float | None = Field(default=None, ge=0, le=999999999999.99, allow_inf_nan=False,
                                          validation_alias=AliasChoices("query_min_amount", "min_amount"))
    query_max_amount: float | None = Field(default=None, ge=0, le=999999999999.99, allow_inf_nan=False,
                                          validation_alias=AliasChoices("query_max_amount", "max_amount"))
    query_all_history: bool = False
    query_scope: Literal["specified", "selected_period"] = "specified"
    query_include_details: bool = True
    query_group_by: Literal["category", "merchant"] | None = None
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


def _selected_query_period(draft: SpendingDraft, selected_period_start: date | None) -> tuple[date, date] | None:
    if draft.query_scope != "selected_period" or selected_period_start is None or draft.questions:
        return None
    start = selected_period_start.replace(day=1)
    return start, next_month(start) - timedelta(days=1)


def _query_resolved(draft: SpendingDraft, message: str, selected_period_start: date | None = None) -> bool:
    return (
        draft.query_all_history or draft.query_start is not None or draft.query_end is not None
        or _query_date(draft, message) is not None
        or _resolve_period(message, capture._today()) is not None
        or _selected_query_period(draft, selected_period_start) is not None
    )


def _answer_query(session: Session, user_id: str, draft: SpendingDraft, message: str, locale="en", *, selected_period_start: date | None = None) -> str:
    # A query is answered from owned records; the model never supplies numbers.
    start, end = draft.query_start, draft.query_end
    if start is None and end is None and not draft.query_all_history:
        period = _resolve_period(message, capture._today())
        when = draft.query_date or (None if period else _query_date(draft, message))
        if when is not None:
            start = end = when
        elif period:
            start, end, _ = period
        elif selected := _selected_query_period(draft, selected_period_start):
            start, end = selected
        else:
            return translate("coach_action.query_ask", locale)
    if start is not None and end is not None and start > end:
        return translate("coach_action.query_ask", locale)
    records, count, total, groups = SQLAlchemyTransactionRepository(session).search_expenses(
        user_id, start=start, end=end, categories=draft.query_categories,
        description=draft.query_description, minimum=draft.query_min_amount,
        maximum=draft.query_max_amount, group_by=draft.query_group_by,
    )
    label = (translate("coach_action.query_all", locale) if start is None and end is None
             else str(start or "…") + (" – " + str(end or "…") if start != end else ""))
    if count == 0:
        return translate("coach_action.query_empty", locale, period=label)
    if not draft.query_include_details and not groups:
        return translate("coach_action.query_result", locale, period=label, count=count,
                         total=f"{total:.2f}", detail="")
    if groups:
        items = "\n".join(f"- {name}: SGD {amount:.2f}" for name, amount in groups.items())
    else:
        items = "\n".join(f"- {record.occurred_on}: {record.description} ({record.category}) SGD {float(record.amount):.2f}"
                          for record in records)
    detail = translate("coach_action.query_details", locale, items=items)
    if count > len(records) and not groups:
        detail += translate("coach_action.query_truncated", locale, shown=len(records), count=count)
    return translate("coach_action.query_result", locale, period=label, count=count, total=f"{total:.2f}", detail=detail)


def _save_dated(
    session: Session, user_id: str, dated: list[tuple[TransactionDraftItem, date]], session_id: str, locale="en",
    *, saved_schedules: list[dict] | None = None,
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
                    recurrence=_validated_recurrence(item, when),
                ),
            )
        except SQLAlchemyError:
            session.rollback()
            return (
                CoachResponse(
                    session_id="",
                    selected_agents=["spending"],
                    answer="Sorry, I couldn't save that transaction. Please try again.",
                    agent_results=[],
                    disclaimers=[],
                    audit={"source": "spending_capture", "action_status": "rejected"},
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
                    audit={"source": "spending_capture", "action_status": "rejected"},
                ),
                "",
            )
        DurableLastSavedStore(session, user_id, session_id).remember(
            user_id,
            LastSavedRecord(
                transaction_id=record.id,
                description=item.description,
                category=category,
                amount=item.amount,
                when=when,
                recurring=item.recurring,
                recurrence=record.recurrence,
                obligation_id=record.obligation_id,
            ),
        )
        log_event("transaction.added", source="coach_capture", category=category)
        saved_parts.append(translate("coach_action.saved_item", locale,
            description=item.description, amount=f"{item.amount:.2f}",
            date=when.isoformat(), category=category.capitalize()))
        if record.recurrence:
            recurrence = LedgerRecurrence.model_validate(record.recurrence)
            saved_parts[-1] += " " + _recurrence_item(record.description, float(record.amount), recurrence, locale)
            if saved_schedules is not None:
                saved_schedules.append({"description": record.description,
                    "amount": {"currency": record.currency, "amount": float(record.amount)},
                    "recurrence": recurrence.model_dump(mode="json")})
    from app.services.budget_alert import category_overage_note

    flagged: list[str] = []
    for (item, when), part in zip(dated, saved_parts, strict=True):
        category = " ".join((item.category or "").split()).lower() or classify_category(
            item.description or ""
        )
        note = category_overage_note(session, user_id, when.replace(day=1), category, locale)
        flagged.append(part + (" " + note.strip() if note else ""))
    body = "; ".join(flagged)
    answer = translate("coach_action.saved", locale, items=body)
    return None, answer


def _recurrence_item(description: str, amount: float, recurrence: LedgerRecurrence, locale: str) -> str:
    frequency = translate("coach_action.frequency_" + recurrence.frequency, locale)
    if recurrence.month_end:
        frequency += " (" + translate("ui.text.on_the_last_day_of_the_month", locale) + ")"
    return translate("coach_action.recurrence_item", locale, description=description,
        amount=f"{amount:.2f}", frequency=frequency, interval=recurrence.interval,
        first=recurrence.first_on.isoformat(), next=recurrence.next_due_on.isoformat(),
        last=recurrence.last_on.isoformat() if recurrence.last_on else translate("coach_action.no_end", locale))


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
    session: Session, user_id: str, draft: SpendingDraft, message: str, session_id: str, locale="en", *, save_complete=True
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
    if dated and save_complete:
        error, saved_answer = _save_dated(session, user_id, dated, session_id, locale)
        if error is not None:
            # A failed write keeps the whole record draft pending for a retry.
            return error.answer, list(draft.transactions)
    if questions:
        extra = "Nothing has been saved. " + " ".join(questions)
        if saved_answer:
            extra = saved_answer + " " + extra.replace("Nothing has been saved. ", "")
        return extra, incomplete
    return saved_answer, []


def _validated_recurrence(item: TransactionDraftItem, when: date) -> LedgerRecurrence | None:
    if item.recurrence is None:
        return None
    terms = RecurrenceTerms.model_validate({**item.recurrence.model_dump(),
                                          "first_on": item.recurrence.first_on or when})
    due = terms.next_due_on or next_occurrence(terms, when)
    return LedgerRecurrence.model_validate({**terms.model_dump(), "next_due_on": due})


def preserves_transaction_preview(pending: dict | None) -> bool:
    """Keep explicit previews across read-only turns without extending approval."""
    if not isinstance(pending, dict):
        return False
    draft = pending.get("draft")
    return pending.get("kind") in {"transaction_confirmation", "recurrence_confirmation"} or (
        isinstance(draft, dict) and draft.get("action") == "record"
        and draft.get("persistence_intent") == "preview"
    )


def stage_transaction_draft(
    session: Session, user_id: str, chat, response: CoachResponse, message: str, *, selected_period_start: date | None = None,
) -> None:
    preserve_preview = preserves_transaction_preview(chat.pending_transaction)
    if chat.pending_transaction and not preserve_preview:
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
        # implicit unfinished record is dropped. Explicit previews retain
        # their original approval state and expiry and cannot auto-save.
        if not preserve_preview:
            chat.pending_transaction = None
        return
    try:
        draft = SpendingDraft.model_validate(result.data["spending_draft"])
    except ValidationError:
        if preserve_preview:
            chat.pending_transaction = {**chat.pending_transaction, "ready": False}
        response.answer = (
            "Nothing has been saved. Please provide what you spent, the SGD amount and the date again."
        )
        response.audit["spending_capture"] = "invalid_draft"
        response.audit["action_status"] = "rejected"
        return
    if not draft.is_spending_request:
        # A non-spending message abandons any unfinished record draft so a later
        # bare reply cannot silently save stale spending. Explicit previews
        # remain subject to owned, unexpired confirmation.
        if not preserve_preview:
            chat.pending_transaction = None
        return
    if draft.action == "forecast":
        from app.services.recurring_forecast import handle_recurring_forecast_query
        start, end = draft.query_start, draft.query_end
        period = _resolve_period(message, capture._today()) if start is None and end is None else None
        if period:
            start, end, _ = period
        next_period = re.search(r"\bnext\s+(week|month|year)\b", message, re.IGNORECASE)
        if start is None and end is None and next_period:
            from app.services.recurring_forecast import next_month_range
            today = capture._today()
            if next_period[1].lower() == "month":
                start, end = next_month_range(today)
            elif next_period[1].lower() == "week":
                start = today - timedelta(days=today.weekday()) + timedelta(days=7)
                end = start + timedelta(days=6)
            else:
                start, end = date(today.year + 1, 1, 1), date(today.year + 1, 12, 31)
        try:
            answer = handle_recurring_forecast_query(session, user_id, chat.id,
                response.audit.get("response_locale", "en"), start=start, end=end,
                categories=draft.query_categories, description=draft.query_description,
                minimum=draft.query_min_amount, maximum=draft.query_max_amount)
        except ValueError:
            response.answer = translate("coach_action.forecast_range_ask", response.audit.get("response_locale", "en"))
            response.audit["action_status"] = "needs_input"
        else:
            response.answer = answer.answer
            response.audit.update(answer.audit)
            response.audit["action_status"] = "read_only_forecast" if answer.audit.get("recurring_forecast") else "needs_input"
            result.data["recurring_forecast"] = answer.audit.get("recurring_forecast", {})
        if not preserve_preview:
            chat.pending_transaction = None
        response.audit["spending_capture"] = "read_only_forecast"
        return
    if draft.action == "query":
        response.answer = _answer_query(session, user_id, draft, message, response.audit.get("response_locale", "en"),
                                       selected_period_start=selected_period_start)
        # A resolved lookup clears any older record draft; an unresolved lookup
        # stays pending so a follow-up date (e.g. "3rd Oct") can complete it.
        if _query_resolved(draft, message, selected_period_start):
            if not preserve_preview:
                chat.pending_transaction = None
            response.audit["spending_capture"] = "read_only_query"
            response.audit["action_status"] = "read_only_query"
        else:
            if preserve_preview:
                locale = response.audit.get("response_locale", "en")
                response.answer = translate("coach_action.query_with_pending_preview", locale, **_preview_commands(locale))
            else:
                chat.pending_transaction = _pending(draft)
            response.audit["spending_capture"] = "needs_input"
            response.audit["action_status"] = "needs_input"
        return
    if preserve_preview:
        # A record amendment cannot bypass the confirmation requested for
        # an explicit preview merely by omitting its persistence intent.
        draft = draft.model_copy(update={"persistence_intent": "preview"})
    leftover = _merge_pending(chat, draft)
    has_recurrence = any(item.recurrence is not None for item in leftover.transactions)
    if leftover.persistence_intent == "preview" or has_recurrence:
        locale = response.audit.get("response_locale", "en")
        answer, incomplete = _resolve_record(session, user_id, leftover, message, chat.id, locale, save_complete=False)
        if incomplete or not leftover.transactions:
            chat.pending_transaction = _pending(leftover) if incomplete else None
            response.answer = answer
            response.audit["spending_capture"] = "needs_input"
            response.audit["action_status"] = "needs_input"
            response.audit["action_status"] = "needs_input"
            response.audit["action_status"] = "needs_input"
            return
        try:
            parts = []
            for item in leftover.transactions:
                recurrence = _validated_recurrence(item, item.occurred_on)
                # Validate the exact proposed expense and schedule before showing approval.
                TransactionCreate(description=item.description, category=item.category or classify_category(item.description),
                                  amount=ApplicationMoneyAmount(amount=item.amount), occurred_on=item.occurred_on,
                                  recurring=item.recurring, recurrence=recurrence)
                if recurrence:
                    item.recurring = True
                    item.recurrence = DraftRecurrence.model_validate(recurrence.model_dump())
                    parts.append(_recurrence_item(item.description, item.amount, recurrence, locale))
                else:
                    parts.append(translate("coach_action.saved_item", locale, description=item.description,
                        amount=f"{item.amount:.2f}", date=item.occurred_on.isoformat(), category=item.category or classify_category(item.description)))
        except (ValueError, TypeError):
            chat.pending_transaction = None
            response.answer = translate("coach_action.recurrence_invalid" if has_recurrence else "coach_action.transaction_invalid", locale)
            response.audit["spending_capture"] = "invalid_recurrence" if has_recurrence else "invalid_draft"
            response.audit["action_status"] = "rejected"
            return
        chat.pending_transaction = {**_pending(leftover), "ready": True, "kind": "transaction_confirmation", "locale": locale}
        response.answer = translate("coach_action.recurrence_preview" if has_recurrence else "coach_action.transaction_preview", locale,
                                    items="\n".join(parts), **_preview_commands(locale))
        response.audit["spending_capture"] = "awaiting_confirmation"
        response.audit["action_status"] = "preview"
        return
    answer, incomplete = _resolve_record(session, user_id, leftover, message, chat.id, response.audit.get("response_locale", "en"))
    response.answer = answer
    if incomplete:
        chat.pending_transaction = _pending(leftover.model_copy(update={"transactions": incomplete}))
        response.audit["spending_capture"] = "needs_input"
        response.audit["action_status"] = "needs_input"
    else:
        chat.pending_transaction = None
        response.audit["spending_capture"] = "saved" if leftover.transactions else "needs_input"
        response.audit["action_status"] = "saved" if leftover.transactions else "needs_input"


def _pending(draft: SpendingDraft) -> dict:
    return {
        "draft": draft.model_dump(mode="json"),
        "baseline": None,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }


def _preview_commands(locale):
    return {"confirm": translate("coach_action.transaction_confirm_command", locale),
            "cancel": translate("coach_action.transaction_cancel_command", locale)}


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
    if not (CONFIRM_OR_CANCEL.fullmatch(text) or PREVIEW_CONFIRM.fullmatch(text) or CANCEL.fullmatch(text)):
        return None
    chat = SQLAlchemyChatRepository(session).get_for_update(request.user_id, request.session_id)
    if chat is None or not chat.pending_transaction:
        # Never intercept confirm/cancel words meant for budget or goal drafts.
        return None
    if (preserves_transaction_preview(chat.pending_transaction) and not CANCEL.fullmatch(text)
            and not PREVIEW_CONFIRM.fullmatch(text)):
        # A yes/no answer to an intervening topic cannot approve an older
        # expense preview. Explicit confirmation identifies this operation.
        return None
    saved_schedules = []
    if CANCEL.fullmatch(text):
        chat.pending_transaction = None
        answer = "Transaction cancelled. Nothing was saved."
        action_status = "cancelled"
    elif chat.pending_transaction.get("kind") in {"recurrence_confirmation", "transaction_confirmation"}:
        pending = chat.pending_transaction
        locale = pending.get("locale", "en")
        if not pending.get("ready") or datetime.fromisoformat(pending["expires_at"]) <= datetime.now(UTC):
            chat.pending_transaction = None
            answer = translate("coach_action.transaction_expired", locale)
            action_status = "rejected"
        else:
            try:
                draft = SpendingDraft.model_validate(pending["draft"])
                error, answer = _save_dated(session, request.user_id,
                    [(item, item.occurred_on) for item in draft.transactions], chat.id, locale,
                    saved_schedules=saved_schedules)
                if error is not None:
                    error.audit["action_status"] = "rejected"
                    return error.model_copy(update={"session_id": request.session_id})
                action_status = "saved"
            except (ValueError, TypeError):
                answer = translate("coach_action.transaction_invalid", locale)
                action_status = "rejected"
            chat.pending_transaction = None
    else:
        chat.pending_transaction = None
        answer = (
            "There is nothing waiting to save. Tell me what you spent and how much, "
            "for example 'I spent $5 on chicken rice today'."
        )
        action_status = "no_pending"
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=["spending"],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit={"source": "spending_capture", "action_status": action_status,
               **({"confirmed_recurrences": saved_schedules} if action_status == "saved" and saved_schedules else {})},
    )
