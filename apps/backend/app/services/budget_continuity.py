"""Preview/confirm monthly batches and opt-in, in-app periodic reviews."""

import calendar
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.api.financial_schemas import BudgetUpsert
from app.infrastructure.models import PlanningPreferencesRecord
from app.infrastructure.repositories import SQLAlchemyBudgetRepository
from app.services.budget_capture import _snapshot
from app.services.budget_constraints import Money, cents, constraint_questions, requirements
from app.services.budget_review import build_budget_review
from app.services.financial_workspace import read_section, write_section


def local_today():
    return datetime.now(ZoneInfo("Asia/Singapore")).date()


def add_months(day, months):
    year, index = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, index + 1, min(day.day, calendar.monthrange(year, index + 1)[1]))


class ContinuityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_period: date
    first_period: date
    months: int = Field(ge=1, le=12)
    take_home_income: Money
    savings_target: Money
    carry_rule: Literal["copy_limits", "carry_surplus", "carry_net"]
    allow_overwrite: bool = False

    @model_validator(mode="after")
    def dates(self):
        if self.source_period.day != 1 or self.first_period.day != 1:
            raise ValueError("Source and target dates must be the first day of a month")
        if self.first_period <= self.source_period or self.first_period.year > 9998:
            raise ValueError(
                "Target months must follow the source month and fit the supported calendar"
            )
        return self


class BatchConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=1, max_length=64)
    confirmed: Literal[True]


class ReviewPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    cadence: Literal["weekly", "monthly"]
    next_review_on: date | None
    confirmed: Literal[True]

    @model_validator(mode="after")
    def needs_date(self):
        if self.enabled and self.next_review_on is None:
            raise ValueError("Choose the first review date before enabling reminders")
        return self


class ReviewAcknowledgement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def batch_evidence(session, user_id, request, today):
    repo = SQLAlchemyBudgetRepository(session)
    targets = [add_months(request.first_period, i) for i in range(request.months)]
    return fingerprint(
        {
            "source": _snapshot(repo.get(user_id, request.source_period)),
            "spending": repo.spending_by_category(user_id, request.source_period, currency="SGD")
            if request.carry_rule != "copy_limits"
            else None,
            "targets": {
                str(period): {
                    "saved": _snapshot(repo.get(user_id, period)),
                    "exists": repo.get(user_id, period) is not None,
                    "requirements": requirements(session, user_id, period),
                }
                for period in targets
            },
            "cashflow": read_section(session, user_id, "cashflow"),
            "date": today,
        }
    )


def preview_batch(session, user_id, request, *, today=None):
    today = today or local_today()
    repo = SQLAlchemyBudgetRepository(session)
    source = repo.get(user_id, request.source_period)
    if not source or source.currency != "SGD" or not source.planning:
        raise ValueError(
            "Choose a saved SGD source budget with confirmed income, savings and coverage"
        )
    if request.first_period < today.replace(day=1):
        raise ValueError("New plans must start in the current month or later")
    if request.carry_rule != "copy_limits" and add_months(request.source_period, 1) > today:
        raise ValueError(
            "Carry-forward calculations require a completed source month; choose copy limits for an open month"
        )
    source_limits = {c.category: cents(c.limit_amount) for c in source.categories}
    spending = repo.spending_by_category(user_id, request.source_period, currency="SGD")
    carry = {}
    for name, limit in source_limits.items():
        difference = limit - cents(spending.get(name, 0))
        carry[name] = (
            0
            if request.carry_rule == "copy_limits"
            else max(difference, 0)
            if request.carry_rule == "carry_surplus"
            else max(difference, -limit)
        )
    rows = []
    questions = []
    for index in range(request.months):
        period = add_months(request.first_period, index)
        # Carry is applied once. Later months resume the source limits; no future spending is invented.
        categories = [
            {"category": name, "limit_amount": (limit + (carry[name] if index == 0 else 0)) / 100}
            for name, limit in sorted(source_limits.items())
        ]
        planning = {
            **source.planning,
            "take_home_income": request.take_home_income,
            "savings_target": request.savings_target,
        }
        raw = {
            "period_start": period.isoformat(),
            "currency": "SGD",
            "categories": categories,
            "planning": planning,
        }
        errors = []
        existing = repo.get(user_id, period)
        if existing and not request.allow_overwrite:
            errors.append(
                "A saved plan exists; explicitly allow replacement or choose other months."
            )
        try:
            payload = BudgetUpsert.model_validate(raw)
            errors.extend(
                constraint_questions(
                    session,
                    user_id,
                    period,
                    {c.category: c.limit_amount for c in payload.categories},
                    payload.planning,
                )
            )
        except ValueError as error:
            errors.append(str(error))
        expense_total = sum(cents(c["limit_amount"]) for c in categories)
        unallocated = (
            cents(request.take_home_income) - cents(request.savings_target) - expense_total
        )
        rows.append(
            {
                "budget": raw,
                "replaces_existing": existing is not None,
                "previous": _snapshot(existing) if existing else None,
                "expenses": expense_total / 100,
                "unallocated": max(unallocated, 0) / 100,
                "funding_gap": max(-unallocated, 0) / 100,
                "questions": errors,
            }
        )
        questions.extend(f"{period:%B %Y}: {error}" for error in errors)
    preview = {
        "preview_id": str(uuid4()),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "request": request.model_dump(mode="json"),
        "plans": rows,
        "carry_amounts": {k: v / 100 for k, v in carry.items()},
        "questions": questions,
        "ready": not questions,
        "saved": False,
        "evidence": batch_evidence(session, user_id, request, today),
        "warnings": [
            "Income and savings repeat exactly as supplied for every target month; confirm they are appropriate for each month.",
            "Carry-forward adjusts only the first target month's limits, using recorded gross expenses. It is not cash in an account; missing expenses and unbudgeted categories can overstate surplus.",
            "Later months copy the source limits without further rollover. Month-specific commitments are not copied; existing target-month commitments are enforced.",
            "Saving replaces each listed target plan in full, including its category list and planning settings. No goals, debts, schedules or transactions are changed.",
        ],
    }
    write_section(session, user_id, "pending_batch", preview)
    return preview


def confirm_batch(session, user_id, confirmation, *, today=None):
    # Serialize confirmation of the same stored preview; consume it in the same transaction as all plans.
    record = session.scalar(
        select(PlanningPreferencesRecord)
        .where(PlanningPreferencesRecord.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    pending = (record.data or {}).get("pending_batch") if record else None
    if not pending or pending["preview_id"] != confirmation.preview_id:
        raise ValueError("Preview not found or already consumed; calculate a fresh preview")
    if not pending["ready"] or datetime.fromisoformat(pending["expires_at"]) < datetime.now(UTC):
        raise ValueError("Preview is incomplete or expired; calculate a fresh preview")
    request = ContinuityRequest.model_validate(pending["request"])
    if batch_evidence(session, user_id, request, today or local_today()) != pending["evidence"]:
        raise ValueError(
            "Budget, commitments, schedules, spending or review date changed; calculate a fresh preview"
        )
    payloads = [BudgetUpsert.model_validate(row["budget"]) for row in pending["plans"]]
    # Validate every target before mutating any. A transaction rollback also protects the whole batch.
    for payload in payloads:
        questions = constraint_questions(
            session,
            user_id,
            payload.period_start,
            {c.category: c.limit_amount for c in payload.categories},
            payload.planning,
        )
        if questions:
            raise ValueError(" ".join(questions))
    with session.begin_nested():
        for payload in payloads:
            SQLAlchemyBudgetRepository(session).upsert(user_id, payload)
        write_section(session, user_id, "pending_batch", None)
    return {"saved": True, "periods": [p.period_start.isoformat() for p in payloads]}


def review_due(session, user_id, *, today=None, include_review=False):
    today = today or local_today()
    stored = read_section(session, user_id, "review_preferences")
    if not stored or not stored["enabled"]:
        return {"enabled": False, "due": False}
    prefs = ReviewPreferences.model_validate(stored)
    due = today >= prefs.next_review_on
    period = (
        add_months(today.replace(day=1), -1) if prefs.cadence == "monthly" else today.replace(day=1)
    )
    result = {
        "enabled": True,
        "due": due,
        "cadence": prefs.cadence,
        "next_review_on": prefs.next_review_on.isoformat(),
        "period_start": period.isoformat(),
        "message": "Your budget review is due. Open Budget to review recorded spending and confirm any changes."
        if due
        else "No budget review is due yet.",
    }
    if due and include_review:
        review = build_budget_review(session, user_id, period, today=today)
        result["review"] = review
        result["evidence"] = fingerprint(
            {"preferences": stored, "review": review["evidence_fingerprint"], "date": today}
        )
    return result


def acknowledge_review(session, user_id, request, *, today=None):
    today = today or local_today()
    due = review_due(session, user_id, today=today, include_review=True)
    if not due["due"] or due["evidence"] != request.evidence:
        raise ValueError(
            "This review changed or is no longer due. Open a fresh review before marking it reviewed."
        )
    prefs = ReviewPreferences.model_validate(read_section(session, user_id, "review_preferences"))
    prefs.next_review_on = (
        today + timedelta(days=7) if prefs.cadence == "weekly" else add_months(today, 1)
    )
    write_section(session, user_id, "review_preferences", prefs.model_dump(mode="json"))
    write_section(
        session,
        user_id,
        "last_review",
        {
            "reviewed_on": today.isoformat(),
            "period_start": due["period_start"],
            "evidence": request.evidence,
        },
    )
    return review_due(session, user_id, today=today)
