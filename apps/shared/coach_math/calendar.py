"""The application calendar is Singapore local time, including month boundaries."""

from datetime import datetime, timedelta, timezone

SINGAPORE = timezone(timedelta(hours=8))


def financial_today():
    return datetime.now(SINGAPORE).date()
