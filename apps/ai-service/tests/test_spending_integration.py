"""
Spending Agent Integration Tests (Simplified)
=============================================
Tests the statistical analysis integration with the Spending Agent.

Note: Full agent integration testing requires orchestration setup.
These tests focus on the statistical analysis capabilities.

Run:
    pytest tests/test_spending_integration.py -v
"""

import pytest
from datetime import date
from app.tools.spending_analyzer import analyze_spending_patterns


@pytest.fixture
def test_transactions_anomaly():
    """Test data with clear anomaly."""
    return [
        {"category": "dining", "amount": {"amount": 100.0}, "occurred_on": "2024-04-15"},
        {"category": "dining", "amount": {"amount": 105.0}, "occurred_on": "2024-05-15"},
        {"category": "dining", "amount": {"amount": 98.0}, "occurred_on": "2024-06-15"},
        {"category": "dining", "amount": {"amount": 102.0}, "occurred_on": "2024-07-15"},
        {"category": "dining", "amount": {"amount": 450.0}, "occurred_on": "2024-08-15"},  # Anomaly
    ]


@pytest.fixture
def test_transactions_trend():
    """Test data with clear upward trend."""
    return [
        {"category": "food", "amount": {"amount": 200.0}, "occurred_on": "2024-05-01"},
        {"category": "food", "amount": {"amount": 250.0}, "occurred_on": "2024-06-01"},
        {"category": "food", "amount": {"amount": 320.0}, "occurred_on": "2024-07-01"},
        {"category": "food", "amount": {"amount": 400.0}, "occurred_on": "2024-08-01"},
    ]


def test_statistical_analysis_detects_anomaly(test_transactions_anomaly):
    """
    Verify statistical analysis detects anomalies.
    
    Requirements:
    - Must detect the $450 dining expense as anomaly
    - Z-score must exceed 2.0 threshold
    - Severity must be assigned
    """
    result = analyze_spending_patterns(
        transactions=test_transactions_anomaly,
        current_month_start=date(2024, 8, 1)
    )
    
    # Verify anomalies are detected
    assert "anomalies" in result
    anomalies = result["anomalies"]
    assert len(anomalies) > 0, "Should detect at least one anomaly"
    
    # Verify the anomaly is for dining category
    dining_anomalies = [a for a in anomalies if a.get("category") == "dining"]
    assert len(dining_anomalies) > 0, "Should detect dining anomaly"
    
    # Verify z-score is calculated and exceeds threshold
    anomaly = dining_anomalies[0]
    assert anomaly.get("z_score") is not None
    assert abs(anomaly["z_score"]) > 2.0, "Z-score should exceed 2.0 threshold"
    assert anomaly.get("severity") in ["low", "medium", "high"]


def test_statistical_analysis_detects_trend(test_transactions_trend):
    """
    Verify statistical analysis detects trends.
    
    Requirements:
    - Must detect upward trend in food spending
    - Must calculate correct percentage change
    - Must assign significance level
    """
    result = analyze_spending_patterns(
        transactions=test_transactions_trend,
        current_month_start=date(2024, 8, 1)
    )
    
    # Verify trends are detected
    assert "category_trends" in result
    trends = result["category_trends"]
    
    # Find food trend
    food_trends = [t for t in trends if t.get("category") == "food"]
    assert len(food_trends) > 0, "Should detect food trend"
    
    trend = food_trends[0]
    assert trend.get("direction") == "increased"
    assert trend.get("change_percent") > 20, "Should detect significant increase"
    assert trend.get("significance") in ["low", "moderate", "high"]


def test_statistical_analysis_data_quality():
    """
    Verify data quality assessment.
    
    Requirements:
    - Must report data quality level
    - Must match months of data provided
    """
    # Test with limited data (1 month)
    limited_data = [
        {"category": "food", "amount": {"amount": 100.0}, "occurred_on": "2024-08-01"},
    ]
    
    result = analyze_spending_patterns(
        transactions=limited_data,
        current_month_start=date(2024, 8, 1)
    )
    
    assert "data_quality" in result
    assert result["data_quality"] in ["insufficient", "limited", "good", "excellent"]
    assert "months_analyzed" in result
    assert result["months_analyzed"] == 1


def test_statistical_analysis_temporal_patterns():
    """
    Verify temporal pattern detection.
    
    Requirements:
    - Must detect weekend vs weekday patterns
    - Must calculate variance correctly
    """
    # Create weekend-heavy spending
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
    
    # Verify temporal patterns are detected
    assert "temporal_patterns" in result
    patterns = result["temporal_patterns"]
    
    # Should detect weekend pattern
    weekend_patterns = [p for p in patterns if p.get("pattern_type") == "weekday_weekend"]
    assert len(weekend_patterns) > 0, "Should detect weekend pattern"
    assert weekend_patterns[0].get("variance_percent") > 15


def test_statistical_analysis_no_data():
    """
    Verify graceful handling of empty data.
    
    Requirements:
    - Must not crash with empty input
    - Must report insufficient data quality
    """
    result = analyze_spending_patterns(
        transactions=[],
        current_month_start=date(2024, 8, 1)
    )
    
    assert result["data_quality"] == "insufficient"
    assert result["months_analyzed"] == 0
    assert result["category_trends"] == []
    assert result["anomalies"] == []
