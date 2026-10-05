"""Shared calendar scope for owned budget records and savings calculations."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BudgetScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["default", "periods", "range", "all"] = "default"
    periods: list[date] = Field(default_factory=list, max_length=120)
    start: date | None = None
    end: date | None = None

    @field_validator("periods", "start", "end")
    @classmethod
    def first_of_month(cls, value):
        dates = value if isinstance(value, list) else [value] if value else []
        if any(day.day != 1 for day in dates):
            raise ValueError("Budget periods must be the first day of a month")
        return value

    @model_validator(mode="after")
    def valid_selection(self):
        if self.kind == "periods":
            if not self.periods or self.start or self.end:
                raise ValueError("Specify unique months for a periods scope")
            if len(self.periods) != len(set(self.periods)):
                raise ValueError("Budget months must be unique")
        elif self.kind == "range":
            if self.periods or not self.start or not self.end or self.start > self.end:
                raise ValueError("Supply an ordered inclusive month range")
            if month_number(self.end) - month_number(self.start) >= 120:
                raise ValueError("Select at most 120 months per range")
        elif self.periods or self.start or self.end:
            raise ValueError("Default and all scopes cannot contain dates")
        return self


def month_number(period):
    return period.year * 12 + period.month - 1


def resolve_budget_periods(scope, default_period=None, available_periods=()):
    """Never substitute the default for an explicit scope or a missing month."""
    if scope.kind == "all":
        return sorted(set(available_periods))
    if scope.kind == "periods":
        return sorted(scope.periods)
    if scope.kind == "range":
        return [
            date(number // 12, number % 12 + 1, 1)
            for number in range(month_number(scope.start), month_number(scope.end) + 1)
        ]
    if default_period is None:
        raise ValueError(
            "Which month and year should I use? Select a default month or specify a period."
        )
    return [default_period]


def scoped_capacity(default, catalog, scope, *, unclear=False):
    """Keep different monthly pools separate; a period total is never monthly income."""
    if unclear:
        return {
            "source": "unavailable",
            "explicit_scope": True,
            "reason": "Specify the requested month and year or an unambiguous range.",
        }
    if scope is None or scope.kind == "default":
        return default
    catalog = dict(catalog)
    if default.get("source") == "confirmed_plan" and default.get("period_start"):
        catalog.setdefault(default["period_start"], default)
    periods = resolve_budget_periods(
        scope, available_periods=[date.fromisoformat(p) for p in catalog]
    )
    rows = [
        catalog.get(
            str(p),
            {
                "source": "unavailable",
                "period_start": str(p),
                "reason": "No confirmed planning settings for this month.",
            },
        )
        for p in periods
    ]
    if len(rows) == 1:
        return {**rows[0], "explicit_scope": True}
    known = [row for row in rows if row.get("source") == "confirmed_plan"]
    # Totals are diagnostic amounts over the selected months, never one recurring pool.
    from decimal import Decimal

    total = float(
        sum(
            (Decimal(str(row["estimated_savings_capacity"])) for row in known),
            Decimal(0),
        )
    )
    return {
        "source": "period_plans",
        "explicit_scope": True,
        "currency": "SGD",
        "periods": rows,
        "known_savings_total": total,
        "complete": bool(rows) and len(known) == len(rows),
        "calculation_method": "Each requested month uses its own confirmed savings allocation.",
        "caveat": "Missing months are unavailable, not zero. Period totals are not monthly capacity. Goals share each month's pool.",
    }
