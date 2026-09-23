"""
Spending Insights E2E Test (Standalone)
========================================
Tests the complete spending insights flow without requiring full backend infrastructure.

This test validates:
1. Statistical analysis produces insights
2. Insights have correct structure
3. Dashboard response format is valid

Run:
    python tests/e2e/test_spending_insights_standalone.py -v
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# Add AI service to path
ai_service_path = Path(__file__).parent.parent.parent.parent / "ai-service" / "app"
sys.path.insert(0, str(ai_service_path))

from tools.spending_analyzer import analyze_spending_patterns


def test_dashboard_insights_structure():
    """Verify dashboard insights have correct structure."""
    transactions = [
        {"category": "dining", "amount": {"amount": 100.0}, "occurred_on": "2024-04-15"},
        {"category": "dining", "amount": {"amount": 105.0}, "occurred_on": "2024-05-15"},
        {"category": "dining", "amount": {"amount": 98.0}, "occurred_on": "2024-06-15"},
        {"category": "dining", "amount": {"amount": 102.0}, "occurred_on": "2024-07-15"},
        {"category": "dining", "amount": {"amount": 450.0}, "occurred_on": "2024-08-15"},
    ]
    
    result = analyze_spending_patterns(
        transactions=transactions,
        current_month_start=date(2024, 8, 1)
    )
    
    # Verify result structure
    assert "insights" in result or "category_trends" in result
    assert "anomalies" in result
    assert "data_quality" in result
    
    print("✅ Dashboard insights structure is valid")


def test_anomaly_detection_e2e():
    """Verify anomaly detection works end-to-end."""
    transactions = [
        {"category": "dining", "amount": {"amount": 100.0}, "occurred_on": "2024-04-15"},
        {"category": "dining", "amount": {"amount": 105.0}, "occurred_on": "2024-05-15"},
        {"category": "dining", "amount": {"amount": 98.0}, "occurred_on": "2024-06-15"},
        {"category": "dining", "amount": {"amount": 102.0}, "occurred_on": "2024-07-15"},
        {"category": "dining", "amount": {"amount": 450.0}, "occurred_on": "2024-08-15"},
    ]
    
    result = analyze_spending_patterns(
        transactions=transactions,
        current_month_start=date(2024, 8, 1)
    )
    
    # Should detect the $450 anomaly
    assert len(result["anomalies"]) > 0
    anomaly = result["anomalies"][0]
    assert anomaly["category"] == "dining"
    assert abs(anomaly["z_score"]) > 2.0
    
    print("✅ Anomaly detection works correctly")


def test_trend_analysis_e2e():
    """Verify trend analysis works end-to-end."""
    transactions = [
        {"category": "food", "amount": {"amount": 200.0}, "occurred_on": "2024-05-01"},
        {"category": "food", "amount": {"amount": 250.0}, "occurred_on": "2024-06-01"},
        {"category": "food", "amount": {"amount": 320.0}, "occurred_on": "2024-07-01"},
        {"category": "food", "amount": {"amount": 400.0}, "occurred_on": "2024-08-01"},
    ]
    
    result = analyze_spending_patterns(
        transactions=transactions,
        current_month_start=date(2024, 8, 1)
    )
    
    # Should detect upward trend
    trends = result["category_trends"]
    food_trends = [t for t in trends if t["category"] == "food"]
    assert len(food_trends) > 0
    assert food_trends[0]["direction"] == "increased"
    assert food_trends[0]["change_percent"] > 20
    
    print("✅ Trend analysis works correctly")


def test_data_quality_assessment_e2e():
    """Verify data quality assessment."""
    # Test with limited data
    limited_data = [
        {"category": "food", "amount": {"amount": 100.0}, "occurred_on": "2024-08-01"},
    ]
    
    result = analyze_spending_patterns(
        transactions=limited_data,
        current_month_start=date(2024, 8, 1)
    )
    
    assert result["data_quality"] in ["insufficient", "limited", "good", "excellent"]
    assert result["months_analyzed"] == 1
    
    print("✅ Data quality assessment works correctly")


def test_temporal_patterns_e2e():
    """Verify temporal pattern detection."""
    # Weekend-heavy spending
    transactions = [
        {"category": "food", "amount": {"amount": 50.0}, "occurred_on": "2024-08-03"},  # Saturday
        {"category": "food", "amount": {"amount": 60.0}, "occurred_on": "2024-08-04"},  # Sunday
        {"category": "food", "amount": {"amount": 55.0}, "occurred_on": "2024-08-10"},  # Saturday
        {"category": "food", "amount": {"amount": 65.0}, "occurred_on": "2024-08-11"},  # Sunday
        {"category": "food", "amount": {"amount": 10.0}, "occurred_on": "2024-08-05"},  # Monday
        {"category": "food", "amount": {"amount": 15.0}, "occurred_on": "2024-08-06"},  # Tuesday
    ]
    
    result = analyze_spending_patterns(
        transactions=transactions,
        current_month_start=date(2024, 8, 1)
    )
    
    patterns = result.get("temporal_patterns", [])
    assert len(patterns) > 0
    
    print("✅ Temporal pattern detection works correctly")


def test_empty_data_handling():
    """Verify graceful handling of empty data."""
    result = analyze_spending_patterns(
        transactions=[],
        current_month_start=date(2024, 8, 1)
    )
    
    assert result["data_quality"] == "insufficient"
    assert result["months_analyzed"] == 0
    assert result["category_trends"] == []
    assert result["anomalies"] == []
    
    print("✅ Empty data handling works correctly")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
