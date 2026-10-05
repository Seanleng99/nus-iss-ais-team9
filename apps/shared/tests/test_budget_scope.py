from datetime import date

import pytest
from coach_math.budget_scope import BudgetScope, resolve_budget_periods, scoped_capacity


def test_range_includes_endpoints_across_year_boundary():
    periods = resolve_budget_periods(
        BudgetScope(kind="range", start="2026-11-01", end="2027-02-01"),
        date(2026, 10, 1),
    )
    assert [str(period) for period in periods] == [
        "2026-11-01",
        "2026-12-01",
        "2027-01-01",
        "2027-02-01",
    ]


@pytest.mark.parametrize(
    "values",
    [
        {"kind": "periods", "periods": ["2026-10-02"]},
        {"kind": "range", "start": "2026-12-01", "end": "2026-10-01"},
        {"kind": "range", "start": "2026-10-01"},
        {"kind": "all", "periods": ["2026-10-01"]},
        {"kind": "periods", "periods": ["2026-10-01", "2026-10-01"]},
    ],
)
def test_invalid_scopes_are_rejected(values):
    with pytest.raises(ValueError):
        BudgetScope.model_validate(values)


def test_default_requires_selection_and_all_uses_owned_catalog():
    with pytest.raises(ValueError, match="month and year"):
        resolve_budget_periods(BudgetScope())
    assert resolve_budget_periods(
        BudgetScope(kind="all"), date(2026, 12, 1), [date(2026, 10, 1)]
    ) == [date(2026, 10, 1)]


def test_missing_capacity_is_not_default_or_zero():
    default = {
        "source": "confirmed_plan",
        "period_start": "2026-10-01",
        "estimated_savings_capacity": 800,
    }
    catalog = {default["period_start"]: default}
    scope = BudgetScope(kind="range", start="2026-10-01", end="2026-11-01")
    result = scoped_capacity(default, catalog, scope)
    assert result["known_savings_total"] == 800
    assert not result["complete"]
    assert result["periods"][1]["source"] == "unavailable"
    assert "estimated_savings_capacity" not in result
    assert (
        scoped_capacity(
            default, catalog, BudgetScope(kind="periods", periods=["2026-11-01"])
        )["source"]
        == "unavailable"
    )
