"""Explicit, owned allocations of recorded payments/refunds to bill occurrences.

Stored in the owned planning workspace, so existing export/erasure covers links too.
All amounts are validated in cents; candidates never become links automatically.
"""

from datetime import date, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.infrastructure.models import PlanningPreferencesRecord, TransactionRecord
from app.services.budget_constraints import category, cents
from app.services.cashflow import CashflowSettings, occurs
from app.services.financial_workspace import lock_workspace, read_section, write_section


class MatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: UUID
    schedule_id: str = Field(min_length=1, max_length=64)
    due_on: date
    amount: float = Field(gt=0, le=999999999999.99, multiple_of=0.01, allow_inf_nan=False)
    effect: Literal["payment", "income", "refund_reopens", "refund_reduces_due"]
    spending_treatment: Literal["cash_only", "reduce_expense"] | None = None


class UnlinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link_id: str = Field(min_length=1, max_length=64)


def links(session, user_id):
    return read_section(session, user_id, "reconciliation") or []


def occurrence_balance(schedule, due_on, allocations):
    rows = [
        r for r in allocations if r["schedule_id"] == schedule.id and r["due_on"] == str(due_on)
    ]
    paid = sum(cents(r["amount"]) for r in rows if r["effect"] in {"payment", "income"})
    refunds = sum(cents(r["amount"]) for r in rows if r["effect"].startswith("refund"))
    reductions = sum(cents(r["amount"]) for r in rows if r["effect"] == "refund_reduces_due")
    due = cents(schedule.amount) - reductions
    net_paid = paid - refunds
    if net_paid < 0 or due < 0 or net_paid > due:
        raise ValueError("Allocations exceed this bill or refund more than its recorded payments")
    return {"due": due / 100, "paid": net_paid / 100, "remaining": (due - net_paid) / 100}


def validate_timeline(session, user_id, schedule, due_on, allocations):
    relevant = [
        r for r in allocations if r["schedule_id"] == schedule.id and r["due_on"] == str(due_on)
    ]
    identifiers = {UUID(r["transaction_id"]) for r in relevant}
    records = {
        str(r.id): r.occurred_on
        for r in session.scalars(
            select(TransactionRecord).where(
                TransactionRecord.user_id == user_id, TransactionRecord.id.in_(identifiers)
            )
        )
    }
    for day in sorted(set(records.values())):
        occurrence_balance(
            schedule, due_on, [r for r in relevant if records[r["transaction_id"]] <= day]
        )


def validate_match(session, user_id, request):
    from app.services.budget_continuity import local_today

    raw = read_section(session, user_id, "cashflow")
    config = CashflowSettings.model_validate(raw) if raw else None
    schedule = (
        next((s for s in config.schedules if s.id == request.schedule_id), None) if config else None
    )
    wanted_kind = "income" if request.effect == "income" else "expense"
    if not schedule or schedule.kind != wanted_kind or not occurs(schedule, request.due_on):
        raise ValueError("Choose an owned bill and a valid occurrence due date")
    if request.due_on in schedule.settled_dates:
        raise ValueError(
            "This occurrence was manually settled. Remove that manual settlement before matching records"
        )
    row = session.get(TransactionRecord, request.transaction_id)
    expected = "expense" if request.effect == "payment" else "income" if request.effect == "income" else "refund"
    if expected == "refund" and request.spending_treatment is None:
        raise ValueError("Choose whether this refund affects cash only or reduces category spending in the refund's recorded month")
    if expected != "refund" and request.spending_treatment == "reduce_expense":
        raise ValueError("Only a recorded refund can reduce budget spending")
    if (
        not row
        or row.user_id != user_id
        or row.currency != "SGD"
        or row.transaction_type != expected
    ):
        raise ValueError(
            "Select an owned SGD expense for payment, income for a receipt, or refund for a refund effect"
        )
    if row.occurred_on > local_today():
        raise ValueError("Future-dated records cannot settle a bill before the recorded date")
    allocations = links(session, user_id)
    if len(allocations) >= 5000:
        raise ValueError("The workspace allocation limit is 5000; remove obsolete matches first")
    used = sum(cents(r["amount"]) for r in allocations if r["transaction_id"] == str(row.id))
    if used + cents(request.amount) > cents(row.amount):
        raise ValueError("Match amount exceeds the transaction's unallocated amount")
    before = occurrence_balance(schedule, request.due_on, allocations)
    match = request.model_dump(mode="json")
    after = occurrence_balance(schedule, request.due_on, [*allocations, match])
    validate_timeline(session, user_id, schedule, request.due_on, [*allocations, match])
    return {
        "match": match,
        "bill": schedule.name,
        "transaction": row.description,
        "before": before,
        "after": after,
        "transaction_unallocated": (cents(row.amount) - used - cents(request.amount)) / 100,
    }


def save_match(session, user_id, request):
    lock_workspace(session, user_id)
    preview = validate_match(session, user_id, request)
    row = {"id": str(uuid4()), **preview["match"]}
    write_section(session, user_id, "reconciliation", [*links(session, user_id), row])
    return row


def validate_unlink(session, user_id, request):
    allocations = links(session, user_id)
    row = next((r for r in allocations if r["id"] == request.link_id), None)
    if not row:
        raise ValueError("Choose an existing match belonging to this profile")
    remaining = [r for r in allocations if r["id"] != request.link_id]
    config = CashflowSettings.model_validate(read_section(session, user_id, "cashflow"))
    schedule = next(s for s in config.schedules if s.id == row["schedule_id"])
    occurrence_balance(schedule, date.fromisoformat(row["due_on"]), remaining)
    validate_timeline(session, user_id, schedule, date.fromisoformat(row["due_on"]), remaining)
    return remaining


def unlink(session, user_id, request):
    lock_workspace(session, user_id)
    write_section(session, user_id, "reconciliation", validate_unlink(session, user_id, request))
    return {"removed": request.link_id}


def guard_transaction(session, user_id, transaction_id):
    lock_workspace(session, user_id)
    if any(r["transaction_id"] == str(transaction_id) for r in links(session, user_id)):
        raise ValueError("Remove this transaction's bill matches before editing or deleting it")


def validate_settings(session, user_id, config):
    prior = read_section(session, user_id, "cashflow")
    old = {s.id: s for s in CashflowSettings.model_validate(prior).schedules} if prior else {}
    new = {s.id: s for s in config.schedules}
    for row in links(session, user_id):
        before, after = old.get(row["schedule_id"]), new.get(row["schedule_id"])
        if (
            not before
            or not after
            or before.model_dump(exclude={"name", "settled_dates"})
            != after.model_dump(exclude={"name", "settled_dates"})
        ):
            raise ValueError("Remove matches before changing or deleting a matched bill's terms")
        if date.fromisoformat(row["due_on"]) in after.settled_dates:
            raise ValueError("A matched occurrence cannot also be manually settled")
    record = session.get(PlanningPreferencesRecord, user_id)
    for key, value in (record.data if record else {}).items():
        if not key.startswith("constraints:") or not value:
            continue
        for debt in value["policy"].get("debts", []):
            bill_id = debt.get("schedule_id")
            if bill_id and (
                bill_id not in new
                or new[bill_id].kind != "expense"
                or category(new[bill_id].category) != debt["category"]
            ):
                raise ValueError(
                    "Revise linked debt commitments before deleting this bill or changing its category/type"
                )
    return config


def save_settings(session, user_id, config):
    lock_workspace(session, user_id)
    validate_settings(session, user_id, config)
    return write_section(session, user_id, "cashflow", config.model_dump(mode="json"))


def reconciliation_context(session, user_id, *, search="", offset=0):
    query = select(TransactionRecord).where(TransactionRecord.user_id == user_id,
        TransactionRecord.currency == "SGD", TransactionRecord.transaction_type.in_(["expense", "refund", "income"]))
    if search:
        query = query.where(TransactionRecord.description.icontains(search, autoescape=True))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(session.scalars(query.order_by(TransactionRecord.occurred_on.desc(), TransactionRecord.id).offset(offset).limit(100)))
    allocated = links(session, user_id)
    return {"links": allocated, "offset": offset, "total": total, "has_more": offset + len(rows) < total,
        "transactions": [{"id":str(r.id), "description":r.description, "category":r.category,
            "occurred_on":str(r.occurred_on), "type":r.transaction_type, "amount":float(r.amount),
            "unallocated":(cents(r.amount)-sum(cents(a["amount"]) for a in allocated if a["transaction_id"]==str(r.id)))/100} for r in rows],
        "coverage":"Owned SGD expense/refund/income records, 100 per page. Search or page for older records. Suggestions require explicit selection and confirmation."}


def match_candidates(session, user_id, transaction_id):
    row=session.get(TransactionRecord,transaction_id)
    if not row or row.user_id != user_id or row.currency != "SGD" or row.transaction_type not in {"expense","income","refund"}:
        raise ValueError("Select an owned SGD expense, income or refund record")
    raw=read_section(session,user_id,"cashflow")
    if not raw:
        return {"candidates":[],"read_only":True}
    config=CashflowSettings.model_validate(raw)
    allocated=links(session,user_id)
    available=cents(row.amount)-sum(cents(r["amount"]) for r in allocated if r["transaction_id"]==str(row.id))
    candidates=[]
    for schedule in config.schedules:
        if schedule.kind != ("income" if row.transaction_type=="income" else "expense") or category(schedule.category)!=category(row.category):
            continue
        for offset in range(-14,15):
            try:
                day=row.occurred_on+timedelta(days=offset)
            except OverflowError:
                continue
            if not occurs(schedule,day) or day in schedule.settled_dates:
                continue
            balance=occurrence_balance(schedule,day,allocated)
            cap=cents(balance["paid"] if row.transaction_type=="refund" else balance["remaining"])
            amount=min(available,cap)
            if amount<=0:
                continue
            candidates.append({"schedule_id":schedule.id,"name":schedule.name,"due_on":str(day),"suggested_amount":amount/100,
                               "date_distance":abs(offset),"reason":"Same category and occurrence within 14 days; this is not proof of a match."})
    candidates.sort(key=lambda c:(c["date_distance"],c["name"],c["due_on"]))
    return {"candidates":candidates[:100],"read_only":True,"warning":"No match is selected or applied automatically; confirm the exact record, occurrence, amount and refund choices."}


def refund_offsets(session, user_id, period, through=None):
    from app.services.budget_continuity import add_months
    entries=[r for r in links(session,user_id) if r.get("spending_treatment")=="reduce_expense" and r["effect"].startswith("refund")]
    if not entries:
        return {}
    raw=read_section(session,user_id,"cashflow")
    schedules={s.id:s for s in CashflowSettings.model_validate(raw).schedules} if raw else {}
    query=select(TransactionRecord).where(TransactionRecord.user_id==user_id,TransactionRecord.currency=="SGD",
        TransactionRecord.transaction_type=="refund",TransactionRecord.id.in_([UUID(r["transaction_id"]) for r in entries]),
        TransactionRecord.occurred_on>=period,TransactionRecord.occurred_on<add_months(period,1))
    if through is not None:
        query=query.where(TransactionRecord.occurred_on<=through)
    eligible={str(r.id) for r in session.scalars(query)}
    amounts={}
    for r in entries:
        if r["transaction_id"] in eligible and r["schedule_id"] in schedules:
            name=category(schedules[r["schedule_id"]].category)
            amounts[name]=amounts.get(name,0)+cents(r["amount"])
    return amounts
