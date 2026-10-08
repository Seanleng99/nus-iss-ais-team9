"""Read-only projections from the explicitly scheduled ledger evidence supplied by the backend."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from coach_math.calendar import financial_today
from coach_math.recurrence import occurrence_dates


def ledger_forecast(transactions, draft, periods=()):
    start, end = draft.get("query_start"), draft.get("query_end")
    if start and end:
        ranges = [(date.fromisoformat(start), date.fromisoformat(end))]
    elif draft.get("query_date"):
        day = date.fromisoformat(draft["query_date"])
        ranges = [(day, day)]
    elif periods:
        ranges = [(date.fromisoformat(p), date.fromisoformat(p).replace(
            day=calendar.monthrange(date.fromisoformat(p).year, date.fromisoformat(p).month)[1])) for p in periods]
    else:
        start = (financial_today().replace(day=28) + timedelta(days=4)).replace(day=1)
        ranges = [(start, start.replace(day=calendar.monthrange(start.year, start.month)[1]))]
    if any(end < start or (end - start).days > 3660 for start, end in ranges):
        raise ValueError("Choose an ordered forecast range of at most 3660 days")
    rows = [t.model_dump(mode="json") for t in transactions]
    linked, unknown = {}, []
    for row in rows:
        identity = row.get("obligation_id")
        if not identity or not row.get("recurrence"):
            unknown.append(row)
        else:
            linked.setdefault(identity, []).append(row)
    schedules = []
    for payments in linked.values():
        latest_date = max(row["occurred_on"] for row in payments)
        latest = [row for row in payments if row["occurred_on"] == latest_date]
        if any((row["amount"], row["recurrence"]) != (latest[0]["amount"], latest[0]["recurrence"]) for row in latest):
            unknown.append(latest[0])
        else:
            schedules.append(latest[0])
    occurrences = []
    for row in schedules:
        amount = row["amount"]["amount"]
        if row["amount"]["currency"] != "SGD":
            continue
        if draft.get("query_categories") and row["category"].casefold() not in {
                value.casefold() for value in draft["query_categories"]}:
            continue
        if draft.get("query_description") and draft["query_description"].casefold() not in row["description"].casefold():
            continue
        if draft.get("query_min_amount") is not None and amount < draft["query_min_amount"]:
            continue
        if draft.get("query_max_amount") is not None and amount > draft["query_max_amount"]:
            continue
        for start, end in ranges:
            occurrences.extend({"description": row["description"], "category": row["category"],
                "due_on": str(due), "amount": amount} for due in occurrence_dates(row["recurrence"], start, end))
    occurrences.sort(key=lambda row: (row["due_on"], row["description"]))
    return {"periods": [{"start": str(start), "end": str(end)} for start, end in ranges],
        "currency": "SGD", "total": float(sum((Decimal(str(row["amount"])) for row in occurrences), Decimal(0))),
        "occurrence_count": len(occurrences), "occurrences": occurrences[:100],
        "details_truncated": len(occurrences) > 100, "unknown_schedule_count": len(unknown),
        "excluded_currencies": sorted({row["amount"]["currency"] for row in rows if row["amount"]["currency"] != "SGD"}),
        "source": "supplied_ledger_recurrence_terms", "records_complete": False,
        "conditional_on_confirmed_terms": True,
        "caveat": "Scheduled ledger projections are not recorded payments or complete household expenses. "
            "Unknown cadence is excluded. The backend separately verifies current schedules, settlements and workspace bills before displaying its authoritative forecast."}
