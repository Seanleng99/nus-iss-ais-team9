"""User-confirmed commitments and deterministic, unsaved funding alternatives."""

import calendar
import math
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.infrastructure.models import FinancialGoalRecord
from app.services.cashflow import CashflowSettings, occurs
from app.services.financial_workspace import read_section, write_section

Money = Annotated[float, Field(ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False)]


def cents(value):
    return int(Decimal(str(value)) * 100)


def category(value):
    return " ".join(value.split()).lower()


class GoalContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal_id: UUID
    monthly_amount: Money


class DebtCommitment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=64)
    balance: Money
    minimum_payment: Money
    schedule_id: str | None = Field(default=None, max_length=64)
    separate_obligation: bool = False


class AllocationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    confirmed: Literal[True]
    minimum_savings: Money
    max_reduction_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    protected_categories: list[str] = Field(max_length=50)
    category_floors: dict[str, Money] = Field(max_length=50)
    goals: list[GoalContribution] = Field(max_length=50)
    debts: list[DebtCommitment] = Field(max_length=50)

    @model_validator(mode="after")
    def validate_policy(self):
        if self.period_start.day != 1:
            raise ValueError("Choose the first day of the planning month")
        names = [
            *self.protected_categories,
            *self.category_floors,
            *(d.category for d in self.debts),
        ]
        if any(not category(n) or len(category(n)) > 64 for n in names):
            raise ValueError("Supply valid category names")
        normalized = {category(k): v for k, v in self.category_floors.items()}
        if len(normalized) != len(self.category_floors):
            raise ValueError("Category floors must be unique")
        self.category_floors = normalized
        self.protected_categories = list(
            dict.fromkeys(category(n) for n in self.protected_categories)
        )
        for debt in self.debts:
            debt.category = category(debt.category)
        if len({g.goal_id for g in self.goals}) != len(self.goals):
            raise ValueError("Choose each goal once")
        return self


class AlternativesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    take_home_income: Money | None = None
    savings_target: Money | None = None


def linked_goals(session, user_id, policy):
    results = []
    for contribution in policy.goals:
        goal = session.get(FinancialGoalRecord, contribution.goal_id)
        if not goal or goal.user_id != user_id or goal.currency != "SGD":
            raise ValueError("Select existing SGD goals belonging to this profile")
        remaining = max(cents(goal.target_amount) - cents(goal.current_amount), 0)
        monthly = cents(contribution.monthly_amount)
        months = math.ceil(remaining / monthly) if monthly else (0 if remaining == 0 else None)
        results.append(
            {
                "goal_id": str(goal.id),
                "name": goal.name,
                "monthly_amount": contribution.monthly_amount,
                "remaining": remaining / 100,
                "estimated_months": months,
                "target_months": goal.target_months,
                "meets_target": months is not None and months <= goal.target_months,
            }
        )
    return results


def validate_debt_links(session, user_id, policy):
    raw = read_section(session, user_id, "cashflow")
    schedules = {s.id: s for s in CashflowSettings.model_validate(raw).schedules} if raw else {}
    used = set()
    for debt in policy.debts:
        if bool(debt.schedule_id) == debt.separate_obligation:
            raise ValueError(f"For debt {debt.name}, choose a linked bill or explicitly mark it as a separate obligation")
        if debt.schedule_id:
            bill = schedules.get(debt.schedule_id)
            if not bill or bill.kind != "expense" or category(bill.category) != debt.category:
                raise ValueError("Choose an owned expense schedule in the debt's category")
            if bill.id in used:
                raise ValueError("A bill can be linked to only one debt commitment per month")
            used.add(bill.id)


def validate_policy(session, user_id, policy):
    from app.infrastructure.repositories import SQLAlchemyBudgetRepository

    record = SQLAlchemyBudgetRepository(session).get(user_id, policy.period_start)
    if not record or record.currency != "SGD" or not record.planning:
        raise ValueError("Save a confirmed SGD monthly plan before setting commitments")
    linked_goals(session, user_id, policy)
    validate_debt_links(session, user_id, policy)
    reference = {item.category: float(item.limit_amount) for item in record.categories}
    if any(n not in reference for n in policy.protected_categories):
        raise ValueError("Protected categories must exist in the saved plan")
    stored = {"policy": policy.model_dump(mode="json"), "reference_limits": reference}
    return stored


def save_policy(session, user_id, policy):
    from app.services.financial_workspace import lock_workspace
    lock_workspace(session, user_id)
    stored = validate_policy(session, user_id, policy)
    write_section(session, user_id, "constraints:" + policy.period_start.isoformat(), stored)
    return stored


def requirements(session, user_id, period):
    stored = read_section(session, user_id, "constraints:" + period.isoformat())
    if not stored:
        return None
    policy = AllocationPolicy.model_validate(stored["policy"])
    goals = linked_goals(session, user_id, policy)
    floors = {name: cents(value) for name, value in policy.category_floors.items()}
    for name, value in stored["reference_limits"].items():
        minimum = int(
            (
                Decimal(cents(value)) * (100 - Decimal(str(policy.max_reduction_percent))) / 100
            ).to_integral_value(rounding=ROUND_CEILING)
        )
        floors[name] = max(
            floors.get(name, 0), cents(value) if name in policy.protected_categories else minimum
        )
    validate_debt_links(session, user_id, policy)
    bills = {}
    by_schedule = {}
    cashflow = read_section(session, user_id, "cashflow")
    if cashflow:
        schedules = CashflowSettings.model_validate(cashflow).schedules
        for offset in range(calendar.monthrange(period.year, period.month)[1]):
            day = period + timedelta(days=offset)
            for schedule in schedules:
                if schedule.kind == "expense" and occurs(schedule, day):
                    name = category(schedule.category)
                    bills[name] = bills.get(name, 0) + cents(schedule.amount)
                    by_schedule[schedule.id] = by_schedule.get(schedule.id, 0) + cents(schedule.amount)
    for debt in policy.debts:
        extra = max(cents(debt.minimum_payment) - by_schedule.get(debt.schedule_id, 0), 0)
        bills[debt.category] = bills.get(debt.category, 0) + extra
    for name, amount in bills.items():
        floors[name] = max(floors.get(name, 0), amount)
    return {
        "floors": floors,
        "savings": max(
            cents(policy.minimum_savings), sum(cents(g.monthly_amount) for g in policy.goals)
        ),
        "goals": goals,
        "debts": [d.model_dump() for d in policy.debts],
    }


def constraint_questions(session, user_id, period, categories, planning):
    try:
        required = requirements(session, user_id, period)
    except ValueError as error:
        return [str(error) + "; update your saved commitments."]
    if not required:
        return []
    questions = [
        f"Keep {name} at least SGD {minimum / 100:,.2f}, or explicitly revise your saved commitments."
        for name, minimum in required["floors"].items()
        if cents(categories.get(name, 0)) < minimum
    ]
    if (
        planning is None
        or planning.savings_target is None
        or cents(planning.savings_target) < required["savings"]
    ):
        questions.append(
            f"Reserve at least SGD {required['savings'] / 100:,.2f} for savings and linked goals, or revise commitments."
        )
    return questions


def build_alternatives(session, user_id, request):
    from app.infrastructure.repositories import SQLAlchemyBudgetRepository
    from app.services.budget_capture import BudgetDraft
    from app.services.budget_scenarios import compare_draft

    record = SQLAlchemyBudgetRepository(session).get(user_id, request.period_start)
    required = requirements(session, user_id, request.period_start)
    if not record or not record.planning or record.currency != "SGD" or not required:
        return {
            "saved": False,
            "results": [],
            "questions": [
                "Save a confirmed SGD plan and confirm this month's protected categories, savings minimum, reduction limit, goals and debt commitments in Budget first."
            ],
        }
    baseline = {item.category: cents(item.limit_amount) for item in record.categories}
    planning = {k: v for k, v in record.planning.items() if k != "version"}
    if request.take_home_income is not None:
        planning["take_home_income"] = request.take_home_income
    savings = max(
        cents(
            request.savings_target
            if request.savings_target is not None
            else planning["savings_target"]
        ),
        required["savings"],
    )
    planning["savings_target"] = savings / 100
    limits = {
        name: max(baseline.get(name, 0), required["floors"].get(name, 0))
        for name in baseline.keys() | required["floors"].keys()
    }
    heads = {name: value - required["floors"].get(name, 0) for name, value in limits.items()}
    gap = max(sum(limits.values()) + savings - cents(planning["take_home_income"]), 0)
    reduction = min(gap, sum(heads.values()))
    scenarios = []
    for name in ("Proportional reductions", "Largest adjustable first"):
        cuts = dict.fromkeys(limits, 0)
        if name == "Proportional reductions" and reduction:
            total = sum(heads.values())
            cuts = {key: reduction * head // total for key, head in heads.items()}
            remainder = reduction - sum(cuts.values())
            for key in sorted(heads, key=lambda k: (-(reduction * heads[k] % total), k)):
                if remainder and cuts[key] < heads[key]:
                    cuts[key] += 1
                    remainder -= 1
        else:
            remaining = reduction
            for key in sorted(heads, key=lambda k: (-heads[k], k)):
                cuts[key] = min(remaining, heads[key])
                remaining -= cuts[key]
        scenarios.append(
            {
                "name": name,
                "categories": [
                    {"category": k, "limit_amount": (v - cuts[k]) / 100}
                    for k, v in sorted(limits.items())
                ],
            }
        )
    draft = BudgetDraft.model_validate(
        {
            "action": "compare",
            "period_start": request.period_start,
            "currency": "SGD",
            "planning": planning,
            "categories": [{"category": k, "limit_amount": v / 100} for k, v in baseline.items()],
            "scenarios": scenarios,
        }
    )
    result = compare_draft(draft)
    for item in result["results"]:
        candidate = BudgetDraft.model_validate(item["draft"])
        from app.services.budget_timing import assess_timing
        item["cashflow"] = assess_timing(session, user_id, request.period_start, {c.category: c.limit_amount for c in candidate.categories}, candidate.planning)
        item["questions"].extend(
            constraint_questions(
                session,
                user_id,
                request.period_start,
                {c.category: c.limit_amount for c in candidate.categories},
                candidate.planning,
            )
        )
    result["commitments"] = {
        **required,
        "floors": {k: v / 100 for k, v in required["floors"].items()},
        "savings": required["savings"] / 100,
    }
    result["questions"].append(
        "Category floors cover the sum of distinct bills and debts. Only explicitly linked debt/bill obligations overlap; the larger monthly requirement is reserved. Goal estimates assume constant contributions, no growth and no withdrawals. Nothing is saved; confirm actual income and expense coverage before saving an option."
    )
    return result
