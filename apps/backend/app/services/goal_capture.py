"""Backend-owned goal previews and atomic, explicit confirmations."""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from coach_i18n import input_pattern, localize_backend_text, request_locale
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from app.api.financial_schemas import GoalCreate
from app.domain.schemas import CoachResponse
from app.infrastructure.models import FinancialGoalRecord
from app.infrastructure.repositories import SQLAlchemyChatRepository, SQLAlchemyGoalRepository


class GoalDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_goal_request: bool = True
    action: Literal["create", "update", "delete"] = "create"
    goal_id: str | None = None
    goal_name: str | None = Field(default=None, max_length=120)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    currency: str = Field(default="SGD", pattern=r"^[A-Z]{3}$")
    target_amount: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    current_amount: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    target_months: int | None = Field(default=None, gt=0, le=600)
    questions: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("currency", mode="before")
    @classmethod
    def default_currency(cls, value):
        return "SGD" if value is None else value


CONFIRM = re.compile(
    input_pattern("backend.services.goal_capture.confirm"), re.IGNORECASE
)
CANCEL = re.compile(input_pattern("backend.services.goal_capture.cancel"), re.IGNORECASE)


def goal_snapshot(record):
    return {
        "name": record.name,
        "currency": record.currency,
        "target_amount": float(record.target_amount),
        "current_amount": float(record.current_amount),
        "target_months": record.target_months,
    }


def _escape(value):
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", str(value))


def _describe(values):
    return (
        f"{_escape(values['name'])}: target {values['currency']} {values['target_amount']:,.2f}; "
        f"currently saved {values['currency']} {values['current_amount']:,.2f}; "
        f"duration {values['target_months']} months"
    )


def _preview(session, user_id, draft):
    baseline = None
    record = None
    questions = list(draft.questions)
    if draft.action != "create":
        query = select(FinancialGoalRecord).where(FinancialGoalRecord.user_id == user_id)
        if draft.goal_id:
            try:
                query = query.where(FinancialGoalRecord.id == UUID(draft.goal_id))
            except ValueError:
                return "Please identify a goal from your Goals page. Nothing changed.", None, None
        records = list(
            session.scalars(query.with_for_update().execution_options(populate_existing=True))
        )
        if not draft.goal_id:
            records = [
                r
                for r in records
                if r.name.strip().casefold() == (draft.goal_name or "").strip().casefold()
            ]
        if len(records) != 1:
            choices = "\n".join(f"- {_describe(goal_snapshot(r))} (ID: {r.id})" for r in records)
            return (
                (
                    "Please specify the exact existing goal name or ID. "
                    "No unique goal was selected; nothing changed."
                    + ("\n" + choices if choices else "")
                ),
                None,
                None,
            )
        record = records[0]
        draft.goal_id = str(record.id)
        baseline = goal_snapshot(record)
    values = dict(baseline or {})
    if draft.action != "delete":
        for field in ("name", "currency", "target_amount", "current_amount", "target_months"):
            value = getattr(draft, field)
            if value is not None:
                values[field] = value
        for field, label in (
            ("name", "goal name"),
            ("target_amount", "target amount"),
            ("current_amount", "currently saved amount (including zero)"),
            ("target_months", "duration in months (1–600)"),
        ):
            if values.get(field) is None or (field == "name" and not values[field].strip()):
                questions.append("Please provide the " + label + ".")
        if baseline and values.get("currency") != baseline["currency"]:
            questions.append("Currency changes require a separate goal; no conversion is assumed.")
        if values.get("currency") != "SGD":
            questions.append("This app supports SGD only. Please provide goal amounts in SGD; no conversion is assumed.")
    if questions:
        return "Nothing changed. " + " ".join(dict.fromkeys(questions)), baseline, None
    if draft.action == "create":
        text = "Create goal preview:\n- " + _describe(values)
    elif draft.action == "update":
        text = (
            "Edit goal preview:\n- Before: "
            + _describe(baseline)
            + "\n- After: "
            + _describe(values)
        )
    else:
        text = (
            "Delete goal preview:\n- "
            + _describe(baseline)
            + "\nThis will permanently delete this goal record."
        )
    if record is not None:
        text += f"\nGoal ID: {record.id}"
    text += "\n\nNothing has changed yet. Reply `confirm goal` to apply this exact change, `cancel goal` to discard it, or provide corrections."
    return text, baseline, values


def stage_goal_draft(session, user_id, chat, response):
    if response.blocked or not any("goal_draft" in result.data for result in response.agent_results):
        return
    before = response.answer
    _stage_goal_draft(session, user_id, chat, response)
    if response.answer != before:
        response.answer = localize_backend_text(response.answer, response.audit.get("response_locale"))


def _stage_goal_draft(session, user_id, chat, response):
    if response.blocked:
        return
    drafts = [
        r.data["goal_draft"]
        for r in response.agent_results
        if r.agent == "goal_strategy" and not r.blocked and "goal_draft" in r.data
    ]
    if not drafts:
        return
    try:
        draft = GoalDraft.model_validate(drafts[0])
    except ValidationError:
        chat.pending_goal = None
        response.answer = (
            "The proposed goal change was invalid. Please restate it. Nothing changed."
        )
        response.audit["action_status"] = "rejected"
        return
    if not draft.is_goal_request:
        return
    if any("budget_draft" in r.data for r in response.agent_results):
        response.answer = "Please request one goal or budget change at a time. Nothing changed."
        chat.pending_goal = None
        chat.pending_budget = None
        response.audit["action_status"] = "rejected"
        return
    text, baseline, values = _preview(session, user_id, draft)
    chat.pending_goal = {
        "draft": draft.model_dump(mode="json"),
        "baseline": baseline,
        "values": values,
        "ready": values is not None,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }
    chat.pending_budget = None
    response.answer = text
    response.audit["action_status"] = "preview" if values is not None else "needs_input"


def handle_goal_confirmation(session, request):
    response = _handle_goal_confirmation(session, request)
    if response:
        response.answer = localize_backend_text(response.answer, request_locale(request))
    return response


def _handle_goal_confirmation(session, request):
    action_status = "rejected"
    confirm = bool(CONFIRM.fullmatch(request.message.strip()))
    cancel = bool(CANCEL.fullmatch(request.message.strip()))
    if not confirm and not cancel:
        return None
    chat = SQLAlchemyChatRepository(session).get_for_update(request.user_id, request.session_id)
    if not chat or not chat.pending_goal:
        if not confirm and request.message.strip().casefold() not in {
            "cancel goal",
            input_pattern("backend.services.goal_capture.cancel_term"),
        }:
            return None
        answer = "There is no pending goal change in this conversation. Nothing changed."
        action_status = "no_pending"
    elif cancel:
        chat.pending_goal = None
        answer = "Goal change cancelled. Nothing changed."
        action_status = "cancelled"
    else:
        pending = chat.pending_goal
        draft = GoalDraft.model_validate(pending["draft"])
        text, baseline, values = _preview(session, request.user_id, draft)
        if values is None:
            answer = text
            chat.pending_goal = {**pending, "ready": False}
            action_status = "needs_input"
        elif (
            not pending["ready"]
            or datetime.fromisoformat(pending["expires_at"]) < datetime.now(UTC)
            or baseline != pending["baseline"]
            or values != pending["values"]
        ):
            answer = "Please review this fresh preview before confirming again.\n\n" + text
            chat.pending_goal = {
                **pending,
                "baseline": baseline,
                "values": values,
                "ready": True,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
            }
            action_status = "preview"
        else:
            repo = SQLAlchemyGoalRepository(session)
            if draft.action == "delete":
                repo.delete(request.user_id, UUID(draft.goal_id))
                answer = "Deleted your confirmed goal."
                action_status = "deleted"
            else:
                payload = GoalCreate(
                    name=values["name"],
                    target_months=values["target_months"],
                    target_amount={
                        "currency": values["currency"],
                        "amount": values["target_amount"],
                    },
                    current_amount={
                        "currency": values["currency"],
                        "amount": values["current_amount"],
                    },
                )
                if draft.action == "create":
                    repo.create(request.user_id, payload)
                else:
                    repo.update(request.user_id, UUID(draft.goal_id), payload)
                answer = "Saved your confirmed goal change. You can review it on the Goals page."
                action_status = "saved"
            chat.pending_goal = None
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=["goal_strategy"],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit={"source": "goal_confirmation", "action_status": action_status},
    )
