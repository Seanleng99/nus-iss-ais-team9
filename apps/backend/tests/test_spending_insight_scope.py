from datetime import date

from app.services.spending_analyzer import _generate_insights

PERIOD = date(2026, 10, 1)


def _analysis_result() -> dict:
    return {
        "category_trends": [
            {
                "category": "dining",
                "current_amount": 320.0,
                "previous_amount": 180.0,
                "change_percent": 77.8,
                "direction": "increased",
                "significance": "high",
            }
        ],
        "anomalies": [
            {
                "category": "travel",
                "amount": 900.0,
                "expected_amount": 200.0,
                "deviation_percent": 350.0,
                "z_score": 3.1,
                "severity": "high",
                "occurred_on": "2026-10-05",
            }
        ],
        "temporal_patterns": [],
        "data_quality": "good",
        "months_analyzed": 6,
    }


def test_trend_insight_names_concrete_month_instead_of_selected_month():
    insights = _generate_insights(_analysis_result(), PERIOD)
    trend = next(insight for insight in insights if insight.insight_type == "trend")
    assert "October 2026" in trend.description
    assert "selected month" not in trend.description.lower()


def test_anomaly_insight_names_concrete_month_of_recorded_total():
    insights = _generate_insights(_analysis_result(), PERIOD)
    anomaly = next(insight for insight in insights if insight.insight_type == "anomaly")
    assert "October 2026" in anomaly.description
