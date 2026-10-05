"""Calendar occurrences anchored to explicitly supplied payment terms."""

import calendar
from datetime import date, timedelta
from typing import Any


def _get(rule: Any, key: str, default=None):
    value = rule.get(key, default) if isinstance(rule, dict) else getattr(rule, key, default)
    if key.endswith("_on") and isinstance(value, str):
        return date.fromisoformat(value)
    return value


def occurs(rule: Any, day: date, *, respect_next_due: bool = True) -> bool:
    first = _get(rule, "first_on")
    last = _get(rule, "last_on")
    next_due = _get(rule, "next_due_on") if respect_next_due else None
    if day < first or (last and day > last) or (next_due and day < next_due):
        return False
    frequency = _get(rule, "frequency")
    interval = _get(rule, "interval", 1)
    if frequency == "once":
        return day == first
    if frequency in {"weekly", "fortnightly"}:
        return (day - first).days % ((7 if frequency == "weekly" else 14) * interval) == 0
    months = (day.year - first.year) * 12 + day.month - first.month
    if frequency == "yearly":
        if months % (12 * interval):
            return False
    elif frequency == "monthly":
        if months % interval:
            return False
    else:
        raise ValueError("Unsupported payment frequency")
    last_day = calendar.monthrange(day.year, day.month)[1]
    return day.day == (last_day if _get(rule, "month_end", False) else min(first.day, last_day))


def occurrence_dates(rule: Any, start: date, end: date) -> list[date]:
    if end < start or (end - start).days > 3660:
        raise ValueError("Choose an ordered date range of at most 3660 days")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)
            if occurs(rule, start + timedelta(days=offset))]


def next_occurrence(rule: Any, after: date) -> date | None:
    """Advance from the original anchor, preserving month ends and leap-day terms."""
    first = _get(rule, "first_on")
    next_due = _get(rule, "next_due_on")
    if next_due and next_due > after:
        after = next_due - timedelta(days=1)
    if _get(rule, "frequency") == "once":
        return first if first > after and occurs(rule, first) else None
    # The supported maximum interval is 120 years. Compute candidate periods
    # directly instead of guessing a day count for months or leap years.
    frequency = _get(rule, "frequency")
    interval = _get(rule, "interval", 1)
    if frequency in {"weekly", "fortnightly"}:
        step = (7 if frequency == "weekly" else 14) * interval
        offset = max(0, (after - first).days // step + 1)
        candidate = first + timedelta(days=offset * step)
    else:
        step = interval * (12 if frequency == "yearly" else 1)
        months = max(0, (after.year - first.year) * 12 + after.month - first.month)
        offset = months // step
        while True:
            target = first.year * 12 + first.month - 1 + offset * step
            year, month0 = divmod(target, 12)
            last_day = calendar.monthrange(year, month0 + 1)[1]
            candidate = date(year, month0 + 1, last_day if _get(rule, "month_end", False) else min(first.day, last_day))
            if candidate > after:
                break
            offset += 1
    return candidate if occurs(rule, candidate) else None
