"""Validate, preview and confirm conversation-scoped budget changes.

Models may propose drafts; only this authenticated backend path writes budgets.
Draft and confirmation state are committed atomically with the chat exchange.
"""

import re
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.api.financial_schemas import BudgetCategoryInput, BudgetPlanSettings, BudgetUpsert
from app.domain.budget_methods import BudgetMethod
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import SQLAlchemyBudgetRepository, SQLAlchemyChatRepository
from app.services.budget_methods import describe_method, method_report
from app.services.budget_planning import PlanningInputs, describe_affordability
from app.services.budget_scenarios import compare_draft, describe_comparison

CONFIRM = re.compile(
    r"^(?:yes|yes please|confirm|confirm budget|save budget|yes[, ]+save(?: it| the budget)?|确认|确认保存)[.!。!\s]*$",
    re.IGNORECASE,
)
CANCEL = re.compile(r"^(?:cancel|cancel budget|no|never mind|取消)[.!。!\s]*$", re.IGNORECASE)


class DraftCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str | None = Field(default=None, max_length=64)
    limit_amount: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: Literal["user", "recorded_spending"] = "user"
    reference_period: date | None = None


class BudgetScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
    take_home_income: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    savings_target: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    categories: list[DraftCategory] = Field(default_factory=list, max_length=50)
    method: BudgetMethod | None = None


class BudgetDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_budget_request: bool = True
    action: Literal["plan", "compare"] = "plan"
    scenarios: list[BudgetScenario] = Field(default_factory=list, max_length=3)
    planning: PlanningInputs | None = None
    period_start: date | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    categories: list[DraftCategory] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=8)

    def missing(self) -> list[str]:
        questions = list(self.questions)
        if self.period_start is None or self.period_start.day != 1:
            questions.append("Which month and year is this budget for (for example, October 2026)?")
        if self.currency != "SGD":
            questions.append(
                "Please specify the currency and provide the limits in SGD; this budget tracks SGD spending."
            )
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
        "planning": record.planning if record else None,
        "categories": {item.category: float(item.limit_amount) for item in record.categories}
        if record
        else {},
    }


def _preview(session: Session, user_id: str, draft: BudgetDraft) -> tuple[str, dict | None]:
    missing = draft.missing()
    if missing:
        if draft.planning:
            missing += draft.planning.questions()
        return "Nothing has been saved. " + " ".join(dict.fromkeys(missing)), None
    payload = draft.payload()
    record = SQLAlchemyBudgetRepository(session).get(user_id, payload.period_start, for_update=True)
    baseline = _snapshot(record)
    if record and record.currency != payload.currency:
        return (
            "The existing budget uses a different currency. Please update it in the Budget page first.",
            None,
        )
    merged = {
        **baseline["categories"],
        **{item.category: item.limit_amount for item in payload.categories},
    }
    if len(merged) > 50:
        return (
            "This would exceed 50 categories. Please remove categories in the Budget page first.",
            None,
        )
    planning = draft.planning or (
        BudgetPlanSettings.model_validate(baseline["planning"]) if baseline["planning"] else None
    )
    questions = draft.planning.questions() if draft.planning else []
    if draft.planning and any(
        name in {"savings", "emergency fund", "investments"} for name in merged
    ):
        questions.append(
            "Separate savings transfers from expense limits before confirming; use the savings allocation and remove any duplicate savings category in Budget."
        )
    lines = [
        f"Budget {'proposal' if planning else 'changes'} for {payload.period_start:%B %Y} (SGD):"
    ]
    for item, original in zip(payload.categories, draft.categories, strict=True):
        old = baseline["categories"].get(item.category)
        change = f"was SGD {old:,.2f}" if old is not None else "new category"
        source = "user-provided"
        if original.source == "recorded_spending":
            source = f"suggested from recorded spending for {original.reference_period or 'an unspecified month'}"
        name = re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", item.category)
        lines.append(f"- {name}: SGD {item.limit_amount:,.2f} ({change}; {source})")
    preserved = {
        key: value
        for key, value in baseline["categories"].items()
        if key not in {item.category for item in payload.categories}
    }
    if preserved:
        lines.append(
            "Existing category limits kept: "
            + "; ".join(f"{key}: SGD {value:,.2f}" for key, value in preserved.items())
        )
    if any(item.source == "recorded_spending" for item in draft.categories):
        lines.append(
            "Recorded spending may be incomplete. These are suggested limits, not verified essential costs. Recurring transactions have not been counted twice."
        )
    if planning:
        report = method_report(merged, planning)
        lines.append(describe_method(report))
        questions.extend(report["questions"])
    fits = True
    if (
        planning
        and planning.take_home_income is not None
        and planning.savings_target is not None
        and planning.income_basis == "take_home"
    ):
        explanation, fits = describe_affordability(merged, planning)
        lines.append(explanation)
    if questions:
        lines.append("Nothing has been saved. " + " ".join(questions))
    elif fits:
        lines.append(
            "Other categories will be kept. Nothing has been saved yet. Reply 'confirm budget' to save, 'cancel' to discard, or send corrections."
        )
    if questions or not fits:
        return "\n\n".join(lines), None
    return "\n\n".join(lines), baseline


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
    if (chat.pending_budget or {}).get("comparison") and draft.action != "compare":
        response.answer = "Choose a stored scenario with 'use scenario NAME' before editing or saving a plan. Nothing was saved."
        return
    previous_planning = (chat.pending_budget or {}).get("draft", {}).get("planning")
    if previous_planning and draft.planning is None:
        response.answer = "Nothing has been saved. Please continue or cancel the pending budget plan; its income, savings and affordability checks cannot be skipped."
        return
    if draft.action == "compare":
        record = (
            SQLAlchemyBudgetRepository(session).get(user_id, draft.period_start)
            if draft.period_start
            else None
        )
        baseline = _snapshot(record)
        if record and record.currency != draft.currency:
            response.answer = "Please confirm the saved budget currency before comparing scenarios. Nothing was saved."
            return
        comparison = compare_draft(draft, baseline["categories"])
        chat.pending_budget = {
            "draft": draft.model_dump(mode="json"),
            "ready": False,
            "baseline": baseline,
            "comparison": comparison,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        }
        response.answer = describe_comparison(comparison)
        response.audit["budget_capture"] = "scenario_comparison"
        response.audit["budget_planner_version"] = "budget-planning-v2"
        return
    answer, baseline = _preview(session, user_id, draft)
    chat.pending_budget = {
        "draft": draft.model_dump(mode="json"),
        "ready": baseline is not None,
        "baseline": baseline,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }
    response.answer = answer
    if draft.planning:
        response.audit["budget_planner_version"] = "budget-planning-v2"
    response.audit["budget_capture"] = (
        "awaiting_confirmation" if baseline is not None else "needs_input"
    )


def handle_budget_confirmation(session: Session, request: CoachRequest) -> CoachResponse | None:
    adoption = re.fullmatch(
        r"use scenario ([A-Za-z0-9][A-Za-z0-9 _-]{0,39})", request.message.strip(), re.IGNORECASE
    )
    if not (
        adoption
        or CONFIRM.fullmatch(request.message.strip())
        or CANCEL.fullmatch(request.message.strip())
    ):
        return None
    chat = SQLAlchemyChatRepository(session).get_for_update(request.user_id, request.session_id)
    if chat is None or not chat.pending_budget:
        if not adoption and request.message.strip().lower() not in {
            "confirm budget",
            "save budget",
        }:
            return None
        answer = "There is no pending budget to confirm in this conversation. Tell me the month, categories and SGD limits first."
    elif adoption:
        pending = chat.pending_budget
        comparison = pending.get("comparison") or {}
        selected = next(
            (
                item
                for item in comparison.get("results", [])
                if item["name"].casefold() == adoption[1].casefold()
            ),
            None,
        )
        if not selected:
            answer = "That scenario is not available. Compare scenarios first and use an exact scenario name. Nothing was saved."
        elif datetime.fromisoformat(pending["expires_at"]) < datetime.now(UTC):
            answer = "This comparison has expired. Request a fresh comparison before adopting a scenario. Nothing was saved."
        else:
            try:
                draft = BudgetDraft.model_validate(selected["draft"])
                record = (
                    SQLAlchemyBudgetRepository(session).get(
                        request.user_id, draft.period_start, for_update=True
                    )
                    if draft.period_start
                    else None
                )
                if _snapshot(record) != pending["baseline"]:
                    answer = "The saved budget changed after this comparison. Request a fresh comparison before adopting a scenario. Nothing was saved."
                else:
                    draft.planning.expenses_confirmed = False
                    # Hypothetical income needs explicit reconfirmation before it becomes a real plan.
                    draft.planning.income_basis = "unknown"
                    preview, _ = _preview(session, request.user_id, draft)
                    chat.pending_budget = {
                        "draft": draft.model_dump(mode="json"),
                        "ready": False,
                        "baseline": None,
                        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
                    }
                    answer = (
                        "Scenario adopted as an unsaved draft. Confirm that its income is your actual take-home amount and review expense coverage.\n\n"
                        + preview
                    )
            except ValidationError:
                answer = "This scenario has invalid or too many categories. Correct the comparison before adopting it. Nothing was saved."
    elif chat.pending_budget.get("comparison") and not CANCEL.fullmatch(request.message.strip()):
        answer = "A comparison cannot be saved. Reply 'use scenario NAME' to choose an unsaved draft first."
    elif (
        chat.pending_budget.get("draft", {}).get("planning")
        and chat.pending_budget.get("baseline") is None
        and request.message.strip().lower() in {"yes", "yes please", "no"}
    ):
        # A yes/no answer to a clarification is not a save or cancellation instruction.
        return None
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
            payload = BudgetUpsert(
                period_start=payload.period_start,
                currency=payload.currency,
                categories=[
                    BudgetCategoryInput(category=key, limit_amount=value)
                    for key, value in merged.items()
                ],
                planning=draft.planning.settings() if draft.planning else baseline["planning"],
            )
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
