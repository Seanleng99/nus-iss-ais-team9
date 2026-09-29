"""Read-only budget review and bounded pace illustrations from owned SGD aggregates."""

import calendar
import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app.infrastructure.repositories import SQLAlchemyBudgetRepository

REVIEW_VERSION = "budget-review-v1"
TRANSFER_CATEGORIES = {"savings", "emergency fund", "investments"}
MIN_ELAPSED_DAYS = 7
MIN_ACTIVITY_DAYS = 3


def money(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_budget_review(session, user_id: str, period_start: date, *, today: date | None = None):
    if period_start.day != 1:
        raise ValueError("Choose the first day of the budget month")
    today = today or datetime.now(ZoneInfo("Asia/Singapore")).date()
    days_in_month = calendar.monthrange(period_start.year, period_start.month)[1]
    month_end = date(period_start.year, period_start.month, days_in_month)
    cutoff = min(today, month_end)
    phase = "future" if today < period_start else "closed" if today > month_end else "current"
    elapsed = max(0, (cutoff - period_start).days + 1)
    remaining_days = max(0, (month_end - cutoff).days) if phase == "current" else 0
    repository = SQLAlchemyBudgetRepository(session)
    record = repository.get(user_id, period_start)
    raw = repository.review_spending(user_id, period_start, cutoff)
    raw = sorted(raw, key=lambda row: (row["category"], row["recurring"]))
    supported = record is None or record.currency == "SGD"
    limits = (
        {item.category: Decimal(str(item.limit_amount)) for item in record.categories}
        if record and supported
        else {}
    )
    warnings = [
        "Recorded transactions may be incomplete. Remaining budget is not an available bank balance or proof that bills are paid."
    ]
    if not supported:
        warnings.append(
            "This review supports SGD budgets only. No currency conversion or adjustments were made."
        )
    if phase == "future":
        warnings.append(
            "This month has not started; future-dated entries are excluded and no pace estimate is available."
        )
    spending = {}
    excluded = Decimal(0)
    for item in raw:
        if item["category"] in TRANSFER_CATEGORIES:
            excluded += Decimal(item["amount"])
            continue
        row = spending.setdefault(
            item["category"],
            {"recurring": Decimal(0), "variable": Decimal(0), "activity_days": 0, "count": 0},
        )
        row["recurring" if item["recurring"] else "variable"] += Decimal(item["amount"])
        row["count"] += item["count"]
        if not item["recurring"]:
            row["activity_days"] = item["activity_days"]
    if excluded:
        warnings.append(
            "Recorded savings, emergency fund and investment transfers are excluded from expense totals; these are not added to your savings allocation."
        )
    rows = []
    for category in sorted(set(limits) | set(spending)):
        evidence = spending.get(
            category,
            {"recurring": Decimal(0), "variable": Decimal(0), "activity_days": 0, "count": 0},
        )
        spent = evidence["recurring"] + evidence["variable"]
        limit = limits.get(category)
        status = (
            "unbudgeted"
            if limit is None
            else "over"
            if spent > limit
            else "approaching"
            if limit > 0 and spent >= limit * Decimal("0.8")
            else "within_recorded_limit"
        )
        estimate = None
        reason = "Pace estimates apply only to an in-progress month."
        if phase == "current":
            if elapsed < MIN_ELAPSED_DAYS:
                reason = "At least seven elapsed days are required for a pace illustration."
            elif evidence["activity_days"] < MIN_ACTIVITY_DAYS:
                reason = "At least three days with non-recurring expense records in this category are required."
            else:
                estimate = evidence["recurring"] + evidence["variable"] / elapsed * days_in_month
                reason = "Recorded recurring amounts held constant; other recorded spending extended at its calendar-day average."
        rows.append(
            {
                "category": category,
                "limit_amount": money(limit) if limit is not None else None,
                "spent": money(spent),
                "remaining": money(limit - spent) if limit is not None else None,
                "status": status,
                "transaction_count": evidence["count"],
                "pace_estimate": money(estimate) if estimate is not None else None,
                "pace_over_limit": money(max(estimate - limit, Decimal(0)))
                if estimate is not None and limit is not None
                else None,
                "pace_note": reason,
                "remaining_per_day": money(max(limit - spent, Decimal(0)) / remaining_days)
                if limit is not None and remaining_days
                else None,
            }
        )
    total_spent = sum((row["recurring"] + row["variable"] for row in spending.values()), Decimal(0))
    total_limit = sum(limits.values(), Decimal(0))
    # A missing category estimate must never be silently counted as zero in an overall forecast.
    total_estimate = (
        money(sum(Decimal(str(row["pace_estimate"])) for row in rows))
        if rows and all(row["pace_estimate"] is not None for row in rows)
        else None
    )
    suggestions = []
    for row in rows:
        if row["status"] in {"over", "unbudgeted"} and row["spent"] > 0:
            suggestions.append(
                {
                    "category": row["category"],
                    "proposed_limit": row["spent"],
                    "reason": "Cover recorded spending only. Review unpaid commitments and future purchases before choosing a full-month limit.",
                }
            )
        elif row["pace_over_limit"] and row["pace_over_limit"] > 0:
            suggestions.append(
                {
                    "category": row["category"],
                    "proposed_limit": None,
                    "reason": "The pace illustration exceeds the limit. Check whether these purchases repeat before changing the budget.",
                }
            )
    if phase == "current":
        warnings.append(
            "Pace is an illustration, not a prediction. One-off purchases, missing transactions and unpaid recurring bills can change the result. Sparse categories have no estimate."
        )
    comparison = None
    if supported and record and suggestions and phase != "future":
        from app.services.budget_capture import BudgetDraft
        from app.services.budget_scenarios import compare_draft

        overrides = [
            {
                "category": row["category"],
                "limit_amount": row["proposed_limit"],
                "source": "recorded_spending",
                "reference_period": period_start.isoformat(),
            }
            for row in suggestions
            if row["proposed_limit"] is not None
        ]
        if overrides and len(set(limits) | {row["category"] for row in overrides}) <= 50:
            planning = {
                key: value for key, value in (record.planning or {}).items() if key != "version"
            }
            planning["expenses_confirmed"] = False
            draft = BudgetDraft.model_validate(
                {
                    "period_start": period_start,
                    "currency": "SGD",
                    "action": "compare",
                    "categories": [
                        {"category": name, "limit_amount": float(value)}
                        for name, value in limits.items()
                    ],
                    "planning": planning,
                    "scenarios": [{"name": "Cover recorded spending", "categories": overrides}],
                }
            )
            comparison = compare_draft(draft)
        elif overrides:
            warnings.append(
                "More than 50 categories would be needed. Choose which categories to include before preparing an adjustment."
            )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "as_of": cutoff.isoformat(),
                "period": period_start.isoformat(),
                "rows": raw,
                "budget": {
                    "currency": record.currency,
                    "limits": {name: money(value) for name, value in limits.items()},
                    "planning": record.planning,
                }
                if record
                else None,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "version": REVIEW_VERSION,
        "period_start": period_start.isoformat(),
        "as_of": cutoff.isoformat(),
        "phase": phase,
        "currency": "SGD",
        "has_budget": record is not None,
        "supported": supported,
        "elapsed_days": elapsed,
        "remaining_days": remaining_days,
        "categories": rows,
        "total_spent": money(total_spent),
        "total_limit": money(total_limit) if record and supported else None,
        "unbudgeted_spent": money(
            sum(
                (Decimal(str(row["spent"])) for row in rows if row["limit_amount"] is None),
                Decimal(0),
            )
        ),
        "total_pace_estimate": total_estimate,
        "excluded_transfers": money(excluded),
        "suggestions": suggestions if supported else [],
        "comparison": comparison,
        "warnings": warnings,
        "evidence_fingerprint": fingerprint,
        "saved": False,
    }


def describe_review(review):
    lines = [
        f"Budget review for {review['period_start']} through {review['as_of']} — nothing was saved.",
        f"Recorded SGD expenses: {review['total_spent']:,.2f}; unbudgeted expenses: {review['unbudgeted_spent']:,.2f}.",
    ]
    if not review["has_budget"]:
        lines.append(
            "No saved budget exists for this month. Supply category limits, income and savings to prepare a plan."
        )
    for row in review["categories"]:
        limit = f"SGD {row['limit_amount']:,.2f}" if row["limit_amount"] is not None else "no limit"
        lines.append(
            f"{row['category']}: recorded SGD {row['spent']:,.2f}; {limit}; {row['status'].replace('_', ' ')}."
        )
        if row["pace_estimate"] is not None:
            lines.append(
                f"Illustrative month-end pace: SGD {row['pace_estimate']:,.2f}. {row['pace_note']}"
            )
    lines.extend(review["warnings"])
    for suggestion in review["suggestions"]:
        lines.append(f"{suggestion['category']}: {suggestion['reason']}")
    return "\n\n".join(lines)
