"""Calendar-based cash flow from explicit schedules, opening balance and typed records."""

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.infrastructure.models import TransactionRecord
from app.services.financial_workspace import read_section


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=64)
    kind: Literal["income", "expense"]
    amount: float = Field(gt=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False)
    first_on: date
    last_on: date | None = None
    frequency: Literal["once", "weekly", "fortnightly", "monthly", "yearly"]
    settled_dates: list[date] = Field(default_factory=list, max_length=366)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.last_on and self.last_on < self.first_on:
            raise ValueError("Schedule end must follow its start")
        return self


class CashflowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opening_on: date
    opening_balance: float = Field(
        ge=-999999999999.99, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False
    )
    currency: Literal["SGD"] = "SGD"
    confirmed: Literal[True]
    schedules: list[Schedule] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_schedules(self):
        if len({item.id for item in self.schedules}) != len(self.schedules):
            raise ValueError("Schedule identifiers must be unique")
        return self


def occurs(schedule, day):
    if day < schedule.first_on or (schedule.last_on and day > schedule.last_on):
        return False
    delta = (day - schedule.first_on).days
    if schedule.frequency == "once":
        return delta == 0
    if schedule.frequency in {"weekly", "fortnightly"}:
        return delta % (7 if schedule.frequency == "weekly" else 14) == 0
    if schedule.frequency == "yearly" and day.month != schedule.first_on.month:
        return False
    return day.day == min(schedule.first_on.day, calendar.monthrange(day.year, day.month)[1])


def project_cashflow(session, user_id, through, *, today=None):
    raw = read_section(session, user_id, "cashflow")
    if raw is None:
        return {
            "needs_input": True,
            "questions": ["Enter a dated opening balance and explicit income/bill schedules."],
            "days": [],
        }
    config = CashflowSettings.model_validate(raw)
    if through < config.opening_on or (through - config.opening_on).days > 365:
        raise ValueError("Choose a horizon from the opening date through at most 365 days later")
    today = today or datetime.now(ZoneInfo("Asia/Singapore")).date()
    actual = list(
        session.scalars(
            select(TransactionRecord).where(
                TransactionRecord.user_id == user_id,
                TransactionRecord.currency == "SGD",
                TransactionRecord.occurred_on >= config.opening_on,
                TransactionRecord.occurred_on <= min(through, today),
            )
        )
    )
    actual_by_day = {}
    for row in actual:
        sign = (
            -1
            if row.transaction_type == "expense"
            else 1
            if row.transaction_type in {"income", "refund"}
            else 0
        )
        actual_by_day[row.occurred_on] = (
            actual_by_day.get(row.occurred_on, Decimal(0)) + Decimal(str(row.amount)) * sign
        )
    balance = Decimal(str(config.opening_balance))
    days = []
    for offset in range((through - config.opening_on).days + 1):
        day = config.opening_on + timedelta(days=offset)
        scheduled = []
        change = actual_by_day.get(day, Decimal(0))
        for schedule in config.schedules:
            if occurs(schedule, day) and day not in schedule.settled_dates:
                signed = Decimal(str(schedule.amount)) * (1 if schedule.kind == "income" else -1)
                change += signed
                scheduled.append(
                    {
                        "id": schedule.id,
                        "name": schedule.name,
                        "kind": schedule.kind,
                        "amount": schedule.amount,
                        "status": "overdue_unconfirmed" if day < today else "scheduled",
                    }
                )
        balance += change
        days.append(
            {
                "date": day.isoformat(),
                "recorded_net": float(actual_by_day.get(day, Decimal(0))),
                "scheduled": scheduled,
                "projected_closing_balance": float(balance),
            }
        )
    lowest = min([config.opening_balance, *(row["projected_closing_balance"] for row in days)])
    return {
        "needs_input": False,
        "currency": "SGD",
        "opening_on": config.opening_on.isoformat(),
        "through": through.isoformat(),
        "days": days,
        "lowest_balance": lowest,
        "closing_balance": float(balance),
        "first_shortfall_on": config.opening_on.isoformat()
        if config.opening_balance < 0
        else next((row["date"] for row in days if row["projected_closing_balance"] < 0), None),
        "warnings": [
            "Opening balance is at the START of its date. Recorded income/refunds add cash; expenses subtract; internal transfers do not change the combined balance.",
            "Unsettled schedules remain projected, including overdue items. Mark each paid/received occurrence settled to avoid counting it again alongside its recorded transaction.",
            "This is a conditional end-of-day projection, not a bank balance. Missing bills, records and within-day timing can change the outcome.",
        ],
    }
