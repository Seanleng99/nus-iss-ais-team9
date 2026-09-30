"""Evaluate budget alternatives using explicitly chosen spending/reserve timing."""
import calendar
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select

from app.infrastructure.models import TransactionRecord
from app.services.budget_constraints import Money, category, cents
from app.services.cashflow import CashflowSettings, project_cashflow
from app.services.financial_workspace import read_section


class TimingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    start_on: date
    minimum_balance: Money
    expense_pattern: Literal["even_daily", "start_of_period", "end_of_period"]
    savings_on: date
    records_complete: Literal[True]
    confirmed: Literal[True]

    @model_validator(mode="after")
    def dates(self):
        if self.period_start.day != 1 or self.start_on.replace(day=1) != self.period_start or self.savings_on.replace(day=1) != self.period_start or self.savings_on < self.start_on:
            raise ValueError("Choose a first-of-month period and spending/reserve dates in that month, with savings on or after the spending start")
        return self


def assess_timing(session, user_id, period, categories, planning, *, today=None):
    from app.services.budget_continuity import local_today
    today = today or local_today()
    raw = read_section(session, user_id, "timing:" + str(period))
    cash = read_section(session, user_id, "cashflow")
    result = {"status": "needs_input", "questions": [], "days": [], "as_of": str(today), "currency": "SGD"}
    if not raw or not cash or not planning:
        result["questions"] = ["Confirm the month's cash-flow timing, minimum balance, opening balance and bill/payday schedules to assess this plan's timing."]
        return result
    timing = TimingSettings.model_validate(raw)
    config = CashflowSettings.model_validate(cash)
    last = period.replace(day=calendar.monthrange(period.year, period.month)[1])
    if config.opening_on > period or timing.start_on < max(today, period) or (last-config.opening_on).days > 365:
        result["questions"] = ["Refresh the spending start date to today or later within this month, and provide an opening balance on or before the month within the 365-day projection horizon."]
        return result
    base = project_cashflow(session, user_id, last, today=today)
    actual = list(session.scalars(select(TransactionRecord).where(TransactionRecord.user_id == user_id,
        TransactionRecord.currency == "SGD", TransactionRecord.occurred_on >= period,
        TransactionRecord.occurred_on <= min(today, last))))
    used = {}
    income = 0
    for t in actual:
        if t.transaction_type == "expense":
            name = category(t.category)
            used[name] = used.get(name, 0) + cents(t.amount)
        elif t.transaction_type == "income":
            income += cents(t.amount)
    from app.services.budget_reconciliation import refund_offsets
    for name, amount in refund_offsets(session, user_id, period, min(today, last)).items():
        used[name] = used.get(name, 0) - amount
    upcoming = []
    for day in base["days"]:
        if day["date"] < str(period):
            continue
        for item in day["scheduled"]:
            schedule = next(s for s in config.schedules if s.id == item["id"])
            if item["kind"] == "expense":
                name = category(schedule.category)
                used[name] = used.get(name, 0) + cents(item["amount"])
                upcoming.append({**item, "due_on": day["date"], "category": name})
            else:
                income += cents(item["amount"])
                if item["status"] == "overdue_unconfirmed":
                    result["questions"].append("Resolve overdue unreceived income before relying on this projection.")
    if income != cents(planning.take_home_income):
        result["questions"].append(f"Dated recorded/scheduled income totals SGD {income/100:,.2f}; supply or revise explicit payday schedules to match this option's take-home income of SGD {planning.take_home_income:,.2f}.")
    remainder = 0
    for name in categories.keys() | used.keys():
        limit, consumed = cents(categories.get(name, 0)), used.get(name, 0)
        if consumed > limit:
            result["questions"].append(f"{name}: recorded spending plus unpaid bills exceeds this option's limit by SGD {(consumed-limit)/100:,.2f}.")
        remainder += max(limit-consumed, 0)
    dates = [timing.start_on + timedelta(days=i) for i in range((last-timing.start_on).days+1)]
    expense_by_date = {}
    if timing.expense_pattern == "even_daily":
        whole, extra = divmod(remainder, len(dates))
        expense_by_date = {str(day): whole + (i < extra) for i, day in enumerate(dates)}
    else:
        expense_by_date[str(dates[0] if timing.expense_pattern == "start_of_period" else dates[-1])] = remainder
    deducted = 0
    days = []
    for row in base["days"]:
        if row["date"] < str(period):
            continue
        deducted += expense_by_date.get(row["date"], 0)
        if row["date"] == str(timing.savings_on):
            deducted += cents(planning.savings_target)
        if row["date"] >= str(timing.start_on):
            days.append({"date": row["date"], "projected_available": (cents(row["projected_closing_balance"])-deducted)/100,
                         "additional_expenses": expense_by_date.get(row["date"], 0)/100})
    lowest = min(d["projected_available"] for d in days)
    first = next((d["date"] for d in days if d["projected_available"] < timing.minimum_balance), None)
    result.update(status="needs_input" if result["questions"] else "shortfall" if first else "within_buffer",
        days=days, lowest_available=lowest, minimum_balance=timing.minimum_balance,
        first_below_buffer_on=first, buffer_gap=max(timing.minimum_balance-lowest, 0),
        upcoming_bills=[b for b in upcoming if b["due_on"] >= str(timing.start_on)],
        unpaid_bills=sum(b["amount"] for b in upcoming),
        savings_reserved=planning.savings_target, assumption=timing.expense_pattern,
        warnings=["Conditional end-of-day spendable balance after reserving savings, not a bank balance. Timing is user-selected; no bill or payday was moved.",
                  "Recorded spending plus unmatched bills consumes each category first. The remaining limits follow your chosen timing. Missing records and within-day ordering can change the result."])
    if first:
        result["suggestions"] = [f"An additional SGD {result['buffer_gap']:,.2f} of available cash would cover the modeled minimum-balance gap.",
            "Review adjustable spending before the shortfall date, or compare another timing choice. Change bill/payday dates only if those changes are actually available and explicitly confirmed."]
    return result


def saved_timing(session, user_id, period):
    from app.api.financial_schemas import BudgetPlanSettings
    from app.infrastructure.repositories import SQLAlchemyBudgetRepository
    record = SQLAlchemyBudgetRepository(session).get(user_id, period)
    return assess_timing(session, user_id, period, {c.category: float(c.limit_amount) for c in record.categories} if record else {},
                         BudgetPlanSettings.model_validate(record.planning) if record and record.planning else None)
