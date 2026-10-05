"""Calendar expense amounts from explicit recurrence terms, without cadence guesses."""

import calendar
import json
from datetime import date, timedelta
from decimal import Decimal

from coach_math.calendar import financial_today
from coach_math.recurrence import occurs


def recurring_month_total(transactions, period_start=None):
    period = (
        date.fromisoformat(period_start)
        if isinstance(period_start, str)
        else period_start or financial_today()
    ).replace(day=1)
    rows = [
        t.model_dump(mode="json") if hasattr(t, "model_dump") else t
        for t in transactions
    ]
    linked, unlinked = {}, []
    for row in rows:
        if row.get("obligation_id"):
            linked.setdefault(row["obligation_id"], []).append(row)
        else:
            unlinked.append(row)
    chosen = list(unlinked)
    end = str(period.replace(day=calendar.monthrange(period.year, period.month)[1]))
    for payments in linked.values():
        eligible = [row for row in payments if row["occurred_on"] <= end]
        if not eligible:
            # A later payment's price is not evidence of this month's price.
            chosen.append({**payments[0], "recurrence": None})
            continue
        latest_date = max(row["occurred_on"] for row in eligible)
        latest = [row for row in eligible if row["occurred_on"] == latest_date]
        row = latest[0]
        if any(
            (r["amount"], r.get("recurrence")) != (row["amount"], row.get("recurrence"))
            for r in latest
        ):
            row = {**row, "recurrence": None}
        chosen.append(row)
    unknown = [
        r
        for r in chosen
        if Decimal(str(r["amount"]["amount"])) > 0
        and (not r.get("recurrence") or r["amount"].get("currency", "SGD") != "SGD")
    ]
    signatures = set()
    for row in unlinked:
        if not row.get("recurrence") or Decimal(str(row["amount"]["amount"])) == 0:
            continue
        signature = json.dumps(
            [
                " ".join(row.get("description", "").casefold().split()),
                row.get("category"),
            ]
        )
        if signature in signatures:
            unknown.append(row)
        signatures.add(signature)
    total = Decimal(0)
    for row in chosen:
        if row in unknown or Decimal(str(row["amount"]["amount"])) == 0:
            continue
        rule = row["recurrence"]
        count = sum(
            occurs(rule, period + timedelta(days=offset), respect_next_due=False)
            for offset in range(calendar.monthrange(period.year, period.month)[1])
        )
        total += Decimal(str(row["amount"]["amount"])) * count
    return {
        "period_start": str(period),
        "monthly_amount": float(total) if not unknown else None,
        "known_monthly_amount": float(total),
        "unknown_schedule_count": len(unknown),
        "input_record_count": len(rows),
        "distinct_schedule_count": len(chosen),
    }
