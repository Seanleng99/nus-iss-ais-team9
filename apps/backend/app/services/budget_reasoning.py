"""Owned monthly expense evidence for conversational budget reasoning."""

from datetime import date

from sqlalchemy import extract, func, select

from app.infrastructure.models import TransactionRecord


def spending_catalog(session, user_id):
    """Aggregate all owned expense months without exporting descriptions or IDs.

    These are recorded gross expenses, not complete household costs or balances.
    Refund reconciliation remains authoritative in the budget review workflow.
    """
    year = extract("year", TransactionRecord.occurred_on)
    month = extract("month", TransactionRecord.occurred_on)
    rows = session.execute(
        select(
            year,
            month,
            TransactionRecord.category,
            TransactionRecord.currency,
            func.sum(TransactionRecord.amount),
            func.count(TransactionRecord.id),
            func.min(TransactionRecord.occurred_on),
            func.max(TransactionRecord.occurred_on),
        )
        .where(
            TransactionRecord.user_id == user_id,
            TransactionRecord.transaction_type == "expense",
        )
        .group_by(year, month, TransactionRecord.category, TransactionRecord.currency)
    )
    catalog = {}
    for y, m, category, currency, total, count, first, last in rows:
        period = str(date(int(y), int(m), 1))
        item = catalog.setdefault(
            period,
            {
                "period_start": period,
                "category_totals": {},
                "transaction_count": 0,
                "currency": "SGD",
                "excluded_currencies": [],
                "first_recorded_on": None,
                "last_recorded_on": None,
            },
        )
        if currency != "SGD":
            item["excluded_currencies"] = sorted({*item["excluded_currencies"], currency})
            continue
        item["category_totals"][category] = float(total)
        item["transaction_count"] += count
        item["first_recorded_on"] = min(item["first_recorded_on"] or str(first), str(first))
        item["last_recorded_on"] = max(item["last_recorded_on"] or str(last), str(last))
    return catalog


def saved_plan_context(session, user_id, record):
    from app.services.budget_capture import _snapshot
    from app.services.budget_constraints import requirements
    from app.services.budget_planning import PlanningInputs, affordability

    data = {"period_start": str(record.period_start), **_snapshot(record)}
    try:
        if record.planning:
            inputs = PlanningInputs.model_validate(
                {k: v for k, v in record.planning.items() if k != "version"}
            )
            data["affordability"] = affordability(data["categories"], inputs)
        required = requirements(session, user_id, record.period_start)
        if required:
            data["restrictions"] = {
                "category_minimums": {k: v / 100 for k, v in required["floors"].items()},
                "savings_minimum": required["savings"] / 100,
            }
    except ValueError:
        data["restriction_status"] = (
            "Saved settings need review; the backend will validate them before changes."
        )
    return data
