from coach_math.budget_baseline import recurring_month_total


def payment(amount=100, frequency="monthly", **changes):
    return {
        "description": "Bill",
        "category": "housing",
        "amount": {"currency": "SGD", "amount": amount},
        "occurred_on": "2026-10-01",
        "obligation_id": "bill",
        "recurrence": {
            "frequency": frequency,
            "first_on": "2026-10-01",
            "next_due_on": "2026-11-01",
            **changes,
        },
    }


def test_repeated_payments_count_one_saved_obligation():
    old = {**payment(1500), "occurred_on": "2026-09-01"}
    result = recurring_month_total([old, payment(1500)], "2026-10-01")
    assert result["monthly_amount"] == 1500
    assert result["distinct_schedule_count"] == 1


def test_weekly_amount_uses_calendar_occurrences_even_when_already_paid():
    # Five Thursdays, including those before next_due_on.
    assert (
        recurring_month_total([payment(30, "weekly")], "2026-10-01")["monthly_amount"]
        == 150
    )


def test_ended_yearly_and_interval_schedules_are_not_monthly_amounts():
    assert (
        recurring_month_total([payment(1200, "yearly")], "2026-11-01")["monthly_amount"]
        == 0
    )
    assert (
        recurring_month_total([payment(200, interval=2)], "2026-11-01")[
            "monthly_amount"
        ]
        == 0
    )
    assert (
        recurring_month_total(
            [payment(30, "weekly", last_on="2026-10-15")], "2026-10-01"
        )["monthly_amount"]
        == 90
    )


def test_unknown_frequency_or_ambiguous_identity_cannot_produce_capacity():
    assert (
        recurring_month_total([{**payment(), "recurrence": None}], "2026-10-01")[
            "monthly_amount"
        ]
        is None
    )
    unlinked = {**payment(), "obligation_id": None}
    assert (
        recurring_month_total([unlinked, unlinked], "2026-10-01")["monthly_amount"]
        is None
    )


def test_distinct_saved_obligations_with_identical_names_are_preserved():
    assert (
        recurring_month_total(
            [payment(), {**payment(), "obligation_id": "second"}], "2026-10-01"
        )["monthly_amount"]
        == 200
    )


def test_conflicting_same_date_terms_and_foreign_currency_require_clarification():
    assert (
        recurring_month_total([payment(), payment(200)], "2026-10-01")["monthly_amount"]
        is None
    )

    assert (
        recurring_month_total(
            [{**payment(), "amount": {"currency": "USD", "amount": 100}}], "2026-10-01"
        )["monthly_amount"]
        is None
    )


def test_explicit_zero_amount_does_not_need_frequency_for_zero_cost():
    assert (
        recurring_month_total([{**payment(0), "recurrence": None}], "2026-10-01")[
            "monthly_amount"
        ]
        == 0
    )


def test_later_price_changes_do_not_rewrite_an_earlier_month():
    old = {**payment(100), "occurred_on": "2026-09-01"}
    new = {**payment(200), "occurred_on": "2026-11-01"}
    assert recurring_month_total([new, old], "2026-10-01")["monthly_amount"] == 100


def test_unlinked_payment_history_needs_identity_even_when_next_due_changes():
    old = {**payment(), "obligation_id": None}
    new = {
        **payment(),
        "obligation_id": None,
        "recurrence": {**payment()["recurrence"], "next_due_on": "2026-12-01"},
    }
    assert recurring_month_total([old, new], "2026-10-01")["monthly_amount"] is None
