"""User-chosen reserves for irregular costs, sharing the savings pool with goals."""
from datetime import date
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.budget_constraints import Money, cents
from app.services.financial_workspace import read_section


class Reserve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    target_amount: Money
    current_reserved: Money
    monthly_contribution: Money
    start_period: date
    due_on: date

    @model_validator(mode="after")
    def dates(self):
        if self.start_period.day != 1 or self.due_on < self.start_period or self.current_reserved > self.target_amount:
            raise ValueError("Choose a first-of-month start before the due date and a current reserve no larger than the target")
        return self


class Reserves(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    reserves: list[Reserve] = Field(max_length=50)

    @model_validator(mode="after")
    def unique(self):
        if len({r.id for r in self.reserves}) != len(self.reserves):
            raise ValueError("Reserve IDs must be unique")
        return self


def reserve_requirement(session, user_id, period):
    raw = read_section(session, user_id, "reserves")
    if not raw:
        return 0
    return sum(cents(r.monthly_contribution) for r in Reserves.model_validate(raw).reserves
               if r.start_period <= period <= r.due_on.replace(day=1))


def reserve_report(settings, period):
    rows = []
    for r in settings.reserves:
        start = max(period, r.start_period)
        months = max((r.due_on.year-start.year)*12 + r.due_on.month-start.month+1, 0)
        remaining = cents(r.target_amount)-cents(r.current_reserved)
        required = ((remaining+months-1)//months)/100 if months else None
        rows.append({**r.model_dump(mode="json"), "months_remaining": months,
            "required_monthly": required, "projected_gap": max(remaining-cents(r.monthly_contribution)*months, 0)/100})
    return {"reserves": rows, "warning": "Contribution estimates assume one contribution per remaining calendar month, including the due month before the due date. Reserves share the savings allocation with goals; balances are user-reported, never inferred or transferred."}
