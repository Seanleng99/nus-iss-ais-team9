"""Read and atomically manage saved budgets over explicit calendar scopes."""

from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from coach_i18n import translate
from coach_math.budget_scope import BudgetScope, resolve_budget_periods
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.financial_schemas import BudgetCategoryInput, BudgetPlanSettings, BudgetUpsert
from app.domain.budget_methods import BudgetMethod
from app.infrastructure.models import MonthlyBudgetRecord
from app.infrastructure.repositories import SQLAlchemyBudgetRepository
from app.services.budget_constraints import constraint_questions, requirements


class PlanningPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    take_home_income: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    savings_target: float | None = Field(
        default=None, ge=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    income_basis: Literal["take_home"] | None = None
    method: BudgetMethod | None = None


class BudgetRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["read", "compare", "edit", "delete"]
    scope: BudgetScope = Field(default_factory=BudgetScope)
    categories: list[BudgetCategoryInput] = Field(default_factory=list, max_length=50)
    remove_categories: list[str] = Field(default_factory=list, max_length=50)
    planning: PlanningPatch | None = None

    @model_validator(mode="after")
    def explicit_changes(self):
        self.remove_categories = [" ".join(name.split()).lower() for name in self.remove_categories]
        names = [item.category for item in self.categories]
        if any(not name or len(name) > 64 for name in self.remove_categories):
            raise ValueError("Supply category names of 1 to 64 characters")
        if len(names) != len(set(names)) or len(self.remove_categories) != len(
            set(self.remove_categories)
        ):
            raise ValueError("Supply one final change per category")
        if set(names) & set(self.remove_categories):
            raise ValueError("A category cannot be changed and removed together")
        changed = bool(
            self.categories
            or self.remove_categories
            or (self.planning and self.planning.model_dump(exclude_none=True))
        )
        if self.action == "edit" and not changed:
            raise ValueError("Specify the category limits, removals or planning fields to change")
        if self.action != "edit" and changed:
            raise ValueError("Read, compare and delete requests cannot include edits")
        return self


def owned_budgets(session, user_id):
    return list(
        session.scalars(
            select(MonthlyBudgetRecord)
            .options(selectinload(MonthlyBudgetRecord.categories))
            .where(MonthlyBudgetRecord.user_id == user_id)
            .order_by(MonthlyBudgetRecord.period_start)
        )
    )


def build_record_change(session, user_id, supplied):
    from app.services.budget_capture import _snapshot

    request = BudgetRecordRequest.model_validate(supplied)
    records = {row.period_start: row for row in owned_budgets(session, user_id)}
    # Coach resolves a default scope before creating the command. Other callers
    # must also choose a month; the server's current month is not authorization.
    periods = resolve_budget_periods(request.scope, available_periods=records)
    if len(periods) > 120 and request.action in {"edit", "delete"}:
        raise ValueError(
            "Select at most 120 saved budgets per request; use explicit ranges for larger histories"
        )
    if not periods:
        if request.action in {"read", "compare"}:
            return request.model_dump(mode="json"), {
                "rows": [],
                "missing_periods": [],
                "totals": {},
            }
        raise ValueError("No saved budgets match this request")
    rows, missing = [], []
    for period in periods:
        record = records.get(period)
        if record is None:
            missing.append(str(period))
            continue
        before = _snapshot(record)
        row = {"period_start": str(period), "before": before}
        if request.action in {"read", "compare"}:
            spent = SQLAlchemyBudgetRepository(session).spending_by_category(
                user_id, period, currency=record.currency
            )
            row["recorded_spending"] = spent
            row["budget_balance"] = float(
                sum((Decimal(str(v)) for v in before["categories"].values()), Decimal(0))
                - sum((Decimal(str(v)) for v in spent.values()), Decimal(0))
            )
        elif request.action == "delete":
            required = requirements(session, user_id, period)
            has_minimums = required and (required["savings"] or any(required["floors"].values()))
            issues = (
                constraint_questions(session, user_id, period, {}, None) if has_minimums else []
            )
            if issues:
                raise ValueError(f"{period}: " + " ".join(issues))
            row["after"] = None
        else:
            if record.currency != "SGD":
                raise ValueError(
                    f"{period}: budget changes support SGD only; no conversion is assumed"
                )
            categories = {**before["categories"]}
            for name in request.remove_categories:
                if name not in categories:
                    raise ValueError(
                        f"{period}: category {name} does not exist; clarify the removal"
                    )
                del categories[name]
            categories.update({item.category: item.limit_amount for item in request.categories})
            planning = deepcopy(before["planning"])
            if request.planning:
                if planning is None:
                    raise ValueError(
                        f"{period}: save a confirmed plan before editing its income, savings or method"
                    )
                patch = request.planning.model_dump(exclude_none=True)
                if "take_home_income" in patch and patch.get("income_basis") != "take_home":
                    raise ValueError("Confirm that the revised income is actual take-home income")
                planning.update(patch)
            if planning:
                planning["method"]["category_groups"] = {
                    k: v
                    for k, v in planning["method"].get("category_groups", {}).items()
                    if k in categories
                }
            payload = BudgetUpsert(
                period_start=period,
                currency=record.currency,
                planning=planning,
                categories=[
                    {"category": name, "limit_amount": amount}
                    for name, amount in categories.items()
                ],
            )
            issues = constraint_questions(session, user_id, period, categories, payload.planning)
            if issues:
                raise ValueError(f"{period}: " + " ".join(issues))
            row["after"] = {
                "currency": payload.currency,
                "categories": {item.category: item.limit_amount for item in payload.categories},
                "planning": payload.planning.model_dump(mode="json") if payload.planning else None,
            }
        rows.append(row)
    if missing and request.action in {"edit", "delete"}:
        raise ValueError(
            "No saved budget for: "
            + ", ".join(missing)
            + ". No changes will be applied; create those budgets or narrow the request."
        )
    totals = {}
    for row in rows:
        currency = row["before"]["currency"]
        total = totals.setdefault(
            currency,
            {
                "limits": Decimal(0),
                "recorded_spending": Decimal(0),
                "savings": Decimal(0),
                "planning_months": 0,
            },
        )
        total["limits"] += sum(
            (Decimal(str(v)) for v in row["before"]["categories"].values()), Decimal(0)
        )
        total["recorded_spending"] += sum(
            (Decimal(str(v)) for v in row.get("recorded_spending", {}).values()), Decimal(0)
        )
        if row["before"]["planning"]:
            total["savings"] += Decimal(str(row["before"]["planning"]["savings_target"]))
            total["planning_months"] += 1
    totals = {
        currency: {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in values.items()
        }
        for currency, values in totals.items()
    }
    return request.model_dump(mode="json"), {
        "rows": rows,
        "missing_periods": missing,
        "totals": totals,
    }


def apply_record_change(session, user_id, target):
    from app.services.budget_capture import _snapshot
    from app.services.budget_history import history
    from app.services.financial_workspace import write_section

    request = BudgetRecordRequest.model_validate(target)
    if request.action not in {"edit", "delete"}:
        raise ValueError("A read or comparison cannot be saved")
    # Revalidate all affected plans before writing, and roll back the complete
    # batch if a repository validation/write fails part way through.
    _, details = build_record_change(session, user_id, target)
    repository = SQLAlchemyBudgetRepository(session)
    with session.begin_nested():
        for row in details["rows"]:
            period = date.fromisoformat(row["period_start"])
            if request.action == "delete":
                record = repository.get(user_id, period, for_update=True)
                snapshot = _snapshot(record)
                # Retain a restorable version without presenting a deleted plan
                # as a currently saved budget or savings-capacity source.
                entries = history(session, user_id, period) + [
                    {
                        "id": str(uuid4()),
                        "saved_at": datetime.now(UTC).isoformat(),
                        "reason": "Plan retained before confirmed deletion",
                        "snapshot": snapshot,
                    }
                ]
                write_section(session, user_id, "history:" + str(period), entries[-50:])
                session.delete(record)
            else:
                after = row["after"]
                repository.upsert(
                    user_id,
                    BudgetUpsert(
                        period_start=period,
                        currency=after["currency"],
                        planning=after["planning"],
                        categories=[
                            {"category": k, "limit_amount": v}
                            for k, v in after["categories"].items()
                        ],
                    ),
                )
        session.flush()
    return {"action": request.action, "periods": [row["period_start"] for row in details["rows"]]}


def describe_record_change(target, details, *, locale="en"):
    import re

    def safe(value):
        return re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", str(value)).replace("\n", " ")

    def amounts(snapshot):
        currency = snapshot["currency"]
        values = "; ".join(
            f"{safe(k)} {currency} {v:,.2f}" for k, v in snapshot["categories"].items()
        ) or translate("budget_action.records_no_limits", locale)
        if snapshot["planning"]:
            plan = BudgetPlanSettings.model_validate(snapshot["planning"])
            values += "; " + translate(
                "budget_action.records_planning",
                locale,
                currency=currency,
                income=f"{plan.take_home_income:,.2f}",
                savings=f"{plan.savings_target:,.2f}",
                method=plan.method.name,
            )
        return values

    reading = target["action"] in {"read", "compare"}
    lines = [
        translate(
            "budget_action.records_compare"
            if target["action"] == "compare"
            else "budget_action.records_read"
            if reading
            else "budget_action.records_preview",
            locale,
        )
    ]
    for row in details["rows"]:
        period = row["period_start"][:7]
        lines.append(
            translate("budget_records.row", locale, period=period, details=amounts(row["before"]))
        )
        if reading:
            spent = sum(Decimal(str(v)) for v in row["recorded_spending"].values())
            lines.append(
                translate(
                    "budget_action.records_spent",
                    locale,
                    currency=row["before"]["currency"],
                    amount=f"{spent:,.2f}",
                )
            )
            lines.append(
                translate(
                    "budget_action.records_balance",
                    locale,
                    currency=row["before"]["currency"],
                    amount=f"{abs(row['budget_balance']):,.2f}",
                    status=translate(
                        "budget_records.over"
                        if row["budget_balance"] < 0
                        else "budget_records.remaining",
                        locale,
                    ),
                )
            )
        else:
            lines.append(
                translate(
                    "budget_action.records_after",
                    locale,
                    period=period,
                    details=translate("budget_action.records_deleted", locale)
                    if row["after"] is None
                    else amounts(row["after"]),
                )
            )
    if not details["rows"]:
        lines.append(translate("budget_action.records_empty", locale))
    if details["missing_periods"]:
        lines.append(
            translate(
                "budget_action.records_missing",
                locale,
                periods=", ".join(details["missing_periods"]),
            )
        )
    if reading:
        for currency, total in details["totals"].items():
            lines.append(
                translate(
                    "budget_action.records_totals",
                    locale,
                    currency=currency,
                    limits=f"{total['limits']:,.2f}",
                    spent=f"{total['recorded_spending']:,.2f}",
                    savings=f"{total['savings']:,.2f}",
                    months=total["planning_months"],
                )
            )
        lines.append(translate("budget_action.records_caveat", locale))
    else:
        lines.append(translate("budget_action.records_preserved", locale))
        lines.append(translate("budget_action.records_confirm", locale))
    return "\n\n".join(lines)
