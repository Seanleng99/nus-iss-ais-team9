"""Explicit recurring terms shared by ledger records and cash-flow schedules."""

import calendar
from datetime import date
from typing import Literal

from coach_math.recurrence import occurs
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RecurrenceTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["once", "weekly", "fortnightly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=120, strict=True)
    month_end: bool = False
    first_on: date
    next_due_on: date | None = None
    last_on: date | None = None

    @model_validator(mode="after")
    def valid_dates(self):
        if self.month_end and (self.frequency not in {"monthly", "yearly"} or
                               self.first_on.day != calendar.monthrange(self.first_on.year, self.first_on.month)[1]):
            raise ValueError("Month-end schedules require a monthly or yearly frequency and a month-end first date")
        if self.last_on and self.last_on < self.first_on:
            raise ValueError("Schedule end must follow its start")
        if self.next_due_on and not occurs(self, self.next_due_on, respect_next_due=False):
            raise ValueError("Next due date must follow the supplied calendar cadence")
        return self


class LedgerRecurrence(RecurrenceTerms):
    next_due_on: date
