from datetime import date

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

from app.api.financial_schemas import SpendingInsight


def _month_label(value: date | str) -> str:
    month = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{month:%B %Y}"


def _generate_insights(analysis_result: dict, period_start: date) -> list[SpendingInsight]:
    """Describe recorded observations without inventing population statistics."""
    insights = []
    selected_month = _month_label(period_start)
    quality = analysis_result.get("data_quality", "insufficient")
    support = {"insufficient": 0.0, "limited": 0.25, "good": 0.5, "excellent": 0.7}[quality]
    qualification = "These observations cover recorded expenses only; missing entries can change the comparison. The support score is a heuristic, not a calibrated probability."
    for trend in analysis_result.get("category_trends", [])[:3]:
        if trend["significance"] not in {"high", "moderate"}:
            continue
        change = trend["change_percent"]
        suffix = f"{abs(change):.0f}%" if change is not None else "from no recorded baseline"
        insights.append(SpendingInsight(
            insight_id=f"trend_{trend['category']}_{trend['direction']}", insight_type="trend",
            title=f"{trend['category'].title()} spending {trend['direction']} {suffix}",
            description=f"Recorded {trend['category']} expenses changed from SGD {trend['previous_amount']:.2f} to SGD {trend['current_amount']:.2f} in {selected_month}.",
            category=trend["category"], confidence=support,
            data_refs=[f"category:{trend['category']}", f"change:{change}"],
            suggested_action="Check whether the comparison includes the same period and any one-off expenses before changing your budget.",
            severity=None, explanation=qualification,
            educational_context="A month-to-month difference does not establish a lasting habit or say whether spending was necessary.",
        ))
    for anomaly in analysis_result.get("anomalies", [])[:2]:
        insights.append(SpendingInsight(
            insight_id=f"anomaly_{anomaly['category']}_{anomaly['occurred_on']}", insight_type="anomaly",
            title=f"Unusual recorded {anomaly['category']} monthly total",
            description=f"In {_month_label(anomaly['occurred_on'])}, the category total of SGD {anomaly['amount']:.2f} differs by {anomaly['deviation_percent']:.0f}% from the observed historical average of SGD {anomaly['expected_amount']:.2f}.",
            category=anomaly["category"], confidence=support,
            data_refs=[f"category_month_total:{anomaly['amount']}", f"expected:{anomaly['expected_amount']}"],
            suggested_action="Review the month's category entries for planned bills, one-off purchases or missing records.",
            severity=anomaly["severity"], explanation=qualification,
            educational_context="An unusual monthly total is an observation, not proof that a transaction is wrong or unaffordable.",
        ))
    for pattern in analysis_result.get("temporal_patterns", [])[:2]:
        insights.append(SpendingInsight(
            insight_id=f"pattern_{pattern['pattern_type']}", insight_type="pattern",
            title=pattern["description"], description=pattern["description"] + " in the observed records.",
            category=None, confidence=min(support, pattern["confidence"]),
            data_refs=[f"pattern_type:{pattern['pattern_type']}", f"variance:{pattern['variance_percent']}%"],
            suggested_action="Check which days were recorded and whether planned payments explain this concentration.",
            severity=None, explanation=qualification,
            educational_context="Day-of-week concentration does not predict future spending from an incomplete history.",
        ))
    return sorted(insights, key=lambda insight: insight.confidence, reverse=True)[:5]
