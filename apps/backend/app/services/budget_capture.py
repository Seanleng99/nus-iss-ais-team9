"""Validate, preview and confirm conversation-scoped budget changes.

Models may propose drafts; only this authenticated backend path writes budgets.
Draft and confirmation state are committed atomically with the chat exchange.
"""

import re
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.api.financial_schemas import BudgetCategoryInput, BudgetUpsert
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import SQLAlchemyBudgetRepository, SQLAlchemyChatRepository

CONFIRM = re.compile(
    r"^(?:yes|yes please|confirm|confirm budget|save budget|yes[, ]+save(?: it| the budget)?|确认|确认保存)[.!。!\s]*$",
    re.IGNORECASE,
)
CANCEL = re.compile(r"^(?:cancel|cancel budget|no|never mind|取消)[.!。!\s]*$", re.IGNORECASE)


class DraftCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = Field(default=None, max_length=64)
    limit_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class BudgetDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_budget_request: bool = True
    period_start: date | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    categories: list[DraftCategory] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=8)

    def missing(self) -> list[str]:
        questions = list(self.questions)
        if self.period_start is None or self.period_start.day != 1:
            questions.append("Which month and year is this budget for (for example, October 2026)?")
        if self.currency != "SGD":
            questions.append("Please specify the currency and provide the limits in SGD; this budget tracks SGD spending.")
        if not self.categories:
            questions.append("Which categories and monthly limits would you like to save?")
        names = []
        for index, item in enumerate(self.categories, 1):
            name = " ".join((item.category or "").split()).lower()
            if not name:
                questions.append(f"What is the category for budget item {index}?")
            else:
                names.append(name)
            if item.limit_amount is not None and (
                item.limit_amount > 999999999999.99
                or round(item.limit_amount, 2) != item.limit_amount
            ):
                questions.append(
                    f"Please provide {name or f'item {index}'} as an SGD amount with at most two decimal places, below 1 trillion."
                )
            if item.limit_amount is None:
                questions.append(f"What is the monthly limit for {name or f'item {index}'}?")
        if len(set(names)) != len(names):
            questions.append(
                "Please provide one monthly limit per category; duplicate categories were supplied."
            )
        return list(dict.fromkeys(questions))

    def payload(self) -> BudgetUpsert:
        return BudgetUpsert(
            period_start=self.period_start,
            currency=self.currency,
            categories=[BudgetCategoryInput(**item.model_dump()) for item in self.categories],
        )


def _snapshot(record) -> dict:
    return {
        "currency": record.currency if record else "SGD",
        "categories": {item.category: float(item.limit_amount) for item in record.categories}
        if record
        else {},
    }


def _preview(session: Session, user_id: str, draft: BudgetDraft) -> tuple[str, dict | None]:
    missing = draft.missing()
    if missing:
        return "Nothing has been saved. " + " ".join(missing), None
    payload = draft.payload()
    record = SQLAlchemyBudgetRepository(session).get(user_id, payload.period_start, for_update=True)
    baseline = _snapshot(record)
    if record and record.currency != payload.currency:
        return (
            "The existing budget uses a different currency. Please update it in the Budget page first.",
            None,
        )
    if len(set(baseline["categories"]) | {item.category for item in payload.categories}) > 50:
        return (
            "This would exceed 50 categories. Please remove categories in the Budget page first.",
            None,
        )
    lines = [f"Please confirm these budget changes for {payload.period_start:%B %Y} (SGD):"]
    for item in payload.categories:
        old = baseline["categories"].get(item.category)
        change = f" (was SGD {old:,.2f})" if old is not None else " (new category)"
        # Categories are user text. Escape Markdown punctuation for the preview.
        name = re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", item.category)
        lines.append(f"- {name}: SGD {item.limit_amount:,.2f}{change}")
    lines.append(
        "Other categories will be kept. Nothing has been saved yet. Reply 'confirm budget' to save, 'cancel' to discard, or send corrections."
    )
    return "\n\n".join([lines[0], "\n".join(lines[1:-1]), lines[-1]]), baseline


def stage_budget_draft(session: Session, user_id: str, chat, response: CoachResponse) -> None:
    # An intervening turn can never leave an old preview armed for a generic 'yes'.
    if chat.pending_budget:
        chat.pending_budget = {**chat.pending_budget, "ready": False}
    if response.blocked:
        return
    result = next(
        (
            item
            for item in response.agent_results
            if item.agent.value == "budget" and not item.blocked and "budget_draft" in item.data
        ),
        None,
    )
    if result is None:
        return
    try:
        draft = BudgetDraft.model_validate(result.data["budget_draft"])
    except ValidationError:
        response.answer = "Nothing has been saved. Please provide the month, year, category, SGD amount and currency again."
        return
    if not draft.is_budget_request:
        return
    answer, baseline = _preview(session, user_id, draft)
    chat.pending_budget = {
        "draft": draft.model_dump(mode="json"),
        "ready": baseline is not None,
        "baseline": baseline,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }
    response.answer = answer
    response.audit["budget_capture"] = (
        "awaiting_confirmation" if baseline is not None else "needs_input"
    )


def handle_budget_confirmation(session: Session, request: CoachRequest) -> CoachResponse | None:
    if not (
        CONFIRM.fullmatch(request.message.strip()) or CANCEL.fullmatch(request.message.strip())
    ):
        return None
    chat = SQLAlchemyChatRepository(session).get_for_update(request.user_id, request.session_id)
    if chat is None or not chat.pending_budget:
        if request.message.strip().lower() not in {"confirm budget", "save budget"}:
            return None
        answer = "There is no pending budget to confirm in this conversation. Tell me the month, categories and SGD limits first."
    elif CANCEL.fullmatch(request.message.strip()):
        chat.pending_budget = None
        answer = "Budget draft cancelled. Nothing was saved."
    else:
        pending = chat.pending_budget
        draft = BudgetDraft.model_validate(pending["draft"])
        expires = datetime.fromisoformat(pending["expires_at"])
        preview, baseline = _preview(session, request.user_id, draft)
        if baseline is None:
            answer = preview
        elif not pending["ready"] or expires < datetime.now(UTC) or baseline != pending["baseline"]:
            answer = "Please review this fresh preview before confirming.\n\n" + preview
            chat.pending_budget = {
                **pending,
                "ready": True,
                "baseline": baseline,
                "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
            }
        else:
            payload = draft.payload()
            merged = {
                **baseline["categories"],
                **{item.category: item.limit_amount for item in payload.categories},
            }
            payload.categories = [
                BudgetCategoryInput(category=key, limit_amount=value)
                for key, value in merged.items()
            ]
            SQLAlchemyBudgetRepository(session).upsert(request.user_id, payload)
            chat.pending_budget = None
            answer = f"Saved your confirmed budget changes for {payload.period_start:%B %Y}. You can review them on the Budget page."
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=["budget"],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit={"source": "budget_confirmation"},
    )
