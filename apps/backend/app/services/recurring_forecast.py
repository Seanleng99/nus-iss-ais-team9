"""Owned recurring expense forecasts from explicitly confirmed calendar terms."""

import re
from bisect import insort
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from coach_i18n import translate
from coach_math.calendar import financial_today
from coach_math.recurrence import occurrence_dates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.recurrence import LedgerRecurrence
from app.domain.schemas import CoachResponse
from app.infrastructure.models import TransactionRecord
from app.services.cashflow import CashflowSettings
from app.services.financial_workspace import read_section

FORECAST_INTENT_PATTERN = re.compile(
    r"\b(?:estimate|forecast|project(?:ion|ions)?|predict|expect)\b[^?]*\b"
    r"(?:spendings?|expenses?|costs?|bills?|outgoings?)\b"
    r"|\b(?:recurring|monthly)\b[^?]*\b(?:spendings?|expenses?|costs?|bills?|total)\b"
    r"|\b(?:spendings?|expenses?|costs?|bills?)\b[^?]*\b(?:recurring|per month|monthly total)\b",
    re.IGNORECASE,
)
EDUCATION_PATTERN = re.compile(r"\b(?:what is|what are|what's|explain|define|meaning of|difference between)\b", re.IGNORECASE)
POSSESSIVE_PATTERN = re.compile(r"\b(?:my|mine|our|i|me)\b", re.IGNORECASE)
ADD_DIRECTIVE_PATTERN = re.compile(r"\b(?:add|record|log|enter|store)\b", re.IGNORECASE)


def parse_recurring_forecast_query(message: str) -> bool:
    text = message.strip()
    if not re.search(r"\brecurring\b", text, re.IGNORECASE):
        return False
    if re.search(r"\b(?:and|also|then|compare|explain|define)\b", text, re.IGNORECASE):
        return False
    return bool(FORECAST_INTENT_PATTERN.search(text) and not ADD_DIRECTIVE_PATTERN.search(text)
                and not (EDUCATION_PATTERN.search(text) and not POSSESSIVE_PATTERN.search(text)))


def _latest_recurring(records) -> list:
    """Only explicit stable identities establish that two records are one bill."""
    identified, unknown = {}, []
    for record in records:
        if not record.recurring or record.transaction_type != "expense" or record.currency != "SGD":
            continue
        if not record.obligation_id or not record.recurrence:
            unknown.append(record)
            continue
        previous = identified.get(record.obligation_id)
        if previous is None or (record.occurred_on, record.created_at, str(record.id)) > (
                previous.occurred_on, previous.created_at, str(previous.id)):
            identified[record.obligation_id] = record
    return [*identified.values(), *unknown]


def next_month_range(today: date | None = None) -> tuple[date, date]:
    today = today or financial_today()
    start = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start, end


def recurring_expense_forecast(session: Session, user_id: str, start: date, end: date, *,
                               categories=None, description=None, minimum=None, maximum=None) -> dict[str, Any]:
    if start > end or (end - start).days > 3660:
        raise ValueError("Choose an ordered forecast range of at most 3660 days")
    from app.services.budget_reconciliation import links, occurrence_balance

    records = list(session.scalars(select(TransactionRecord).where(
        TransactionRecord.user_id == user_id, TransactionRecord.recurring.is_(True),
        TransactionRecord.transaction_type == "expense", TransactionRecord.currency == "SGD",
    )))
    def matches(name, category, amount):
        return (not categories or category.casefold() in {c.casefold() for c in categories}) and (
            not description or description.casefold() in name.casefold()) and (
            minimum is None or float(amount) >= minimum) and (
            maximum is None or float(amount) <= maximum)

    latest = [r for r in _latest_recurring(records) if matches(r.description, r.category, r.amount)]
    unknown = [r for r in latest if not r.recurrence or not r.obligation_id]
    raw = read_section(session, user_id, "cashflow")
    config = CashflowSettings.model_validate(raw) if raw else None
    schedules = [s for s in config.schedules if s.kind == "expense" and matches(s.name, s.category, s.amount)] if config else []
    workspace_ids = {s.id for s in config.schedules} if config else set()
    allocations = links(session, user_id)
    occurrences = []
    total = Decimal(0)
    count = 0
    schedule_count = len(schedules)

    def append(identity, description, category, due, amount):
        nonlocal total, count
        amount = Decimal(str(amount))
        if amount <= 0:
            return
        total += amount
        count += 1
        insort(occurrences, {"obligation_id": identity, "description": description,
                            "category": category, "due_on": due.isoformat(), "amount": float(amount)},
               key=lambda row: (row["due_on"], row["description"], row["obligation_id"]))
        if len(occurrences) > 100:
            occurrences.pop()

    for schedule in schedules:
        for due in occurrence_dates(schedule, start, end):
            if due not in schedule.settled_dates:
                append(schedule.id, schedule.name, schedule.category, due,
                       occurrence_balance(schedule, due, allocations)["remaining"])
    for record in latest:
        if not record.recurrence or not record.obligation_id or record.obligation_id in workspace_ids:
            continue
        rule = LedgerRecurrence.model_validate(record.recurrence)
        schedule_count += 1
        for due in occurrence_dates(rule, start, end):
            append(record.obligation_id, record.description, record.category, due, record.amount)
    return {
        "start": start.isoformat(), "end": end.isoformat(), "currency": "SGD",
        "total": float(total), "occurrence_count": count, "schedule_count": schedule_count,
        "occurrences": occurrences, "details_truncated": count > len(occurrences),
        "unknown_cadence_count": len(unknown),
        "unknown_recorded_total": float(sum((Decimal(str(r.amount)) for r in unknown), Decimal(0))),
        "unknown_records": [{"description": r.description, "amount": float(r.amount)} for r in unknown[:50]],
        "records_complete": False, "conditional_on_confirmed_terms": True,
    }


def handle_recurring_forecast_query(
    session: Session, user_id: str, session_id: str, locale="en", *, start: date | None = None,
    end: date | None = None,
    categories=None, description=None, minimum=None, maximum=None,
) -> CoachResponse:
    default_start, default_end = next_month_range()
    if (start is None) != (end is None):
        return CoachResponse(session_id=session_id, selected_agents=[],
                             answer=translate("coach_action.forecast_range_ask", locale), agent_results=[],
                             disclaimers=[], audit={"source": "recurring_forecast"})
    data = recurring_expense_forecast(session, user_id, start or default_start, end or default_end,
                                      categories=categories, description=description, minimum=minimum, maximum=maximum)
    if not data["schedule_count"] and not data["unknown_cadence_count"]:
        answer = translate("coach_action.recurring_none", locale)
    elif not data["schedule_count"]:
        items = ", ".join(f"{r['description']} SGD {r['amount']:.2f}" for r in data["unknown_records"])
        answer = translate("coach_action.recurring_summary", locale,
                           total=f"{data['unknown_recorded_total']:.2f}", items=items)
        if data["unknown_cadence_count"] > len(data["unknown_records"]):
            answer += translate("coach_action.query_truncated", locale, shown=len(data["unknown_records"]), count=data["unknown_cadence_count"])
    else:
        detail = "\n".join(f"- {r['due_on']}: {r['description']} SGD {r['amount']:.2f}" for r in data["occurrences"])
        answer = translate("coach_action.forecast_result", locale, start=data["start"], end=data["end"],
                           total=f"{data['total']:.2f}", count=data["occurrence_count"], items=detail)
        if data["details_truncated"]:
            answer += translate("coach_action.query_truncated", locale, shown=len(data["occurrences"]), count=data["occurrence_count"])
        if data["unknown_cadence_count"]:
            answer += " " + translate("coach_action.forecast_unknown", locale, count=data["unknown_cadence_count"])
    return CoachResponse(session_id=session_id, selected_agents=[], answer=answer, agent_results=[],
                         disclaimers=[], audit={"source": "recurring_forecast", "cadence_known": data["unknown_cadence_count"] == 0,
                                                "forecast_available": bool(data["schedule_count"]), "recurring_forecast": data})
