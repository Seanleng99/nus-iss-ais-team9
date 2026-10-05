"""Shared deterministic analysis used by the Coach and insights API."""

from coach_math.spending_analysis import (  # noqa: F401
    AnomalyResult,
    TemporalPatternResult,
    TrendResult,
    aggregate_by_category,
    analyze_spending_patterns,
    assess_data_quality,
    calculate_months_available,
    compute_category_trends,
    day_name,
    detect_anomalies,
    detect_temporal_patterns,
    filter_transactions,
    group_by_category_monthly,
    is_weekday,
)
