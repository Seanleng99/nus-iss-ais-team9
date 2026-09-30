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
from app.services.budget_review import build_budget_review, describe_review
from app.services.budget_scenarios import compare_draft, describe_comparison
from app.services.budget_workspace import WorkspaceChange

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
    action: Literal["plan", "compare", "review", "alternatives", "continuity", "workspace"] = "plan"
    workspace: WorkspaceChange | None = None
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
    # Compute known totals even while non-structural questions remain unresolved.
    missing = draft.model_copy(update={"questions": []}).missing()
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
    questions = [*draft.questions, *(draft.planning.questions() if draft.planning else [])]
    if draft.planning and any(
        name in {"savings", "emergency fund", "investments"} for name in merged
    ):
        questions.append(
            "Separate savings transfers from expense limits before confirming; use the savings allocation and remove any duplicate savings category in Budget."
        )
    from app.services.budget_constraints import constraint_questions
    questions.extend(constraint_questions(session, user_id, payload.period_start, merged, planning))
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
    if draft.action in {"workspace", "continuity"}:
        import json
        previous_workspace = (chat.pending_budget or {}).get("draft", {}).get("workspace")
        if draft.workspace and previous_workspace and draft.workspace.operation == previous_workspace.get("operation"):
            try:
                previous_values = json.loads(previous_workspace["payload_json"])
                new_values = json.loads(draft.workspace.payload_json)
                if isinstance(previous_values, dict) and isinstance(new_values, dict):
                    draft.workspace.payload_json = json.dumps({**previous_values, **new_values})
            except (ValueError, TypeError):
                pass  # Invalid structured data remains subject to authoritative validation.
        from app.services.budget_workspace import describe_preview, preview_change
        pending = {"draft": draft.model_dump(mode="json"), "ready": False,
                   "baseline": None, "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat()}
        try:
            if draft.questions:
                raise ValueError(" ".join(draft.questions))
            if draft.workspace is None:
                raise ValueError("Supply the planning operation and its details. For multiple months: source month/year, first target month/year, number of months, actual take-home income, savings, expense coverage and carry rule. You can also use Plan upcoming months in Budget.")
            pending["workspace_preview"] = preview_change(session, user_id, draft.workspace)
            pending["ready"] = True
            response.answer = describe_preview(pending["workspace_preview"])
        except ValueError as error:
            response.answer = "Nothing has been saved. " + str(error)
        chat.pending_budget = pending
        response.audit["budget_capture"] = "workspace_preview" if pending["ready"] else "needs_input"
        response.audit["budget_workspace_version"] = "budget-workspace-v1"
        return
    if draft.action == "alternatives":
        from app.services.budget_constraints import AlternativesRequest, build_alternatives
        if draft.period_start is None or draft.period_start.day != 1 or draft.questions:
            response.answer = "Please specify the month and year for funded alternatives. " + " ".join(draft.questions)
            if not chat.pending_budget:
                chat.pending_budget = {"draft": draft.model_dump(mode="json"), "ready": False,
                    "baseline": None, "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat()}
            return
        if draft.currency not in {None, "SGD"}:
            response.answer = "Funded alternatives support SGD plans only. Nothing was saved."
            return
        if draft.planning and draft.planning.take_home_income is not None and draft.planning.income_basis != "take_home":
            response.answer = "Please confirm the alternative income is take-home income in SGD after payroll deductions. Nothing was saved."
            return
        try:
            comparison = build_alternatives(session, user_id, AlternativesRequest(
                period_start=draft.period_start,
                take_home_income=draft.planning.take_home_income if draft.planning else None,
                savings_target=draft.planning.savings_target if draft.planning else None))
        except ValueError as error:
            response.answer = str(error) + ". Update your commitments in Budget; nothing was saved."
            return
        record = SQLAlchemyBudgetRepository(session).get(user_id, draft.period_start)
        chat.pending_budget = {"draft": draft.model_dump(mode="json"), "ready": False,
            "baseline": _snapshot(record), "comparison": comparison,
            "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat()}
        response.answer = describe_comparison(comparison)
        response.audit["budget_capture"] = "read_only_alternatives"
        return
    if draft.action == "review":
        if draft.period_start is None or draft.period_start.day != 1 or draft.questions:
            response.answer = (
                "Which month and year should I review? Nothing was changed. "
                + " ".join(draft.questions)
            )
            if not chat.pending_budget:
                chat.pending_budget = {
                    "draft": draft.model_dump(mode="json"),
                    "ready": False,
                    "baseline": None,
                    "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
                }
            return
        if draft.currency not in {None, "SGD"}:
            response.answer = "Budget reviews currently support SGD records only. No conversion or changes were made."
            return
        review = build_budget_review(session, user_id, draft.period_start)
        response.answer = describe_review(review)
        response.audit["budget_review_version"] = review["version"]
        response.audit["budget_capture"] = "read_only_review"
        # Preserve an unrelated pending plan/comparison; a review never replaces it implicitly.
        previous = (chat.pending_budget or {}).get("draft", {})
        if previous and previous.get("action") != "review":
            response.answer += "\n\nYour existing draft was kept. Finish or cancel it before adopting a review adjustment."
            return
        record = SQLAlchemyBudgetRepository(session).get(user_id, draft.period_start)
        chat.pending_budget = {
            "draft": draft.model_dump(mode="json"),
            "ready": False,
            "baseline": _snapshot(record),
            "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        }
        if review["comparison"]:
            chat.pending_budget = {
                **chat.pending_budget,
                "comparison": review["comparison"],
                "review_evidence": review["evidence_fingerprint"],
            }
            response.answer += "\n\n" + describe_comparison(review["comparison"])
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
        response.audit["budget_planner_version"] = "budget-planning-v4"
        return
    review_origin = (chat.pending_budget or {}).get("review_origin")
    if review_origin and (
        draft.period_start is None
        or draft.period_start.isoformat() != review_origin["period_start"]
        or build_budget_review(session, user_id, draft.period_start)["evidence_fingerprint"]
        != review_origin["evidence"]
    ):
        response.answer = "This adjustment's review is out of date or the month changed. Cancel the pending draft and request a fresh review. Nothing was saved."
        return
    answer, baseline = _preview(session, user_id, draft)
    chat.pending_budget = {
        "draft": draft.model_dump(mode="json"),
        "ready": baseline is not None,
        "review_origin": review_origin,
        "baseline": baseline,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
    }
    response.answer = answer
    if draft.planning:
        response.audit["budget_planner_version"] = "budget-planning-v4"
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
                evidence_changed = bool(pending.get("review_evidence")) and (
                    build_budget_review(session, request.user_id, draft.period_start)[
                        "evidence_fingerprint"
                    ]
                    != pending["review_evidence"]
                )
                if evidence_changed:
                    answer = "Spending records or the review date changed. Request a fresh budget review before adopting an adjustment. Nothing was saved."
                elif _snapshot(record) != pending["baseline"]:
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
                        "review_origin": {
                            "period_start": draft.period_start.isoformat(),
                            "evidence": pending["review_evidence"],
                        }
                        if pending.get("review_evidence")
                        else None,
                        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
                    }
                    answer = (
                        "Scenario adopted as an unsaved draft. Confirm that its income is your actual take-home amount and review expense coverage.\n\n"
                        + preview
                    )
            except ValidationError:
                answer = "This scenario has invalid or too many categories. Correct the comparison before adopting it. Nothing was saved."
    elif chat.pending_budget.get("draft", {}).get("action") in {"workspace", "continuity"}:
        from app.services.budget_workspace import confirm_change
        if CANCEL.fullmatch(request.message.strip()):
            chat.pending_budget = None
            answer = "Planning draft cancelled. Nothing was saved."
        elif not chat.pending_budget.get("ready"):
            if request.message.strip().lower() in {"yes", "yes please"}:
                return None
            answer = "Complete the missing planning details and review a fresh preview before confirming. Nothing was saved."
        else:
            try:
                confirm_change(session, request.user_id, chat.pending_budget["workspace_preview"])
                chat.pending_budget = None
                answer = "Saved your confirmed planning changes. Review them on the Budget page."
            except ValueError as error:
                chat.pending_budget = {**chat.pending_budget, "ready": False}
                answer = "Nothing was saved. " + str(error)
    elif chat.pending_budget.get("comparison") and not CANCEL.fullmatch(request.message.strip()):
        answer = "A comparison cannot be saved. Reply 'use scenario NAME' to choose an unsaved draft first."
    elif chat.pending_budget.get("draft", {}).get("action") == "review" and not CANCEL.fullmatch(
        request.message.strip()
    ):
        answer = "A review cannot be saved. Request a proposed adjustment or supply explicit budget limits first."
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
        review_origin = pending.get("review_origin")
        if (
            review_origin
            and build_budget_review(session, request.user_id, draft.period_start)[
                "evidence_fingerprint"
            ]
            != review_origin["evidence"]
        ):
            answer = "This adjustment's review is out of date. Cancel the pending draft and request a fresh review. Nothing was saved."
        elif baseline is None:
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
