from datetime import date

import pytest

from app.tools.spending_analyzer import (
    analyze_spending_patterns,
    compute_category_trends,
    detect_anomalies,
    detect_temporal_patterns,
)


class TestCategoryTrends:
    """Test month-over-month trend calculations."""
    
    def test_category_trend_calculation(self):
        """Verify MoM % change calculation."""
        current = [
            {"category": "food", "amount": {"amount": 200.0}},
            {"category": "food", "amount": {"amount": 150.0}},
        ]
        previous = [
            {"category": "food", "amount": {"amount": 250.0}},
        ]
        
        trends = compute_category_trends(current, previous)
        
        assert len(trends) == 1
        assert trends[0].category == "food"
        assert trends[0].current_amount == 350.0
        assert trends[0].previous_amount == 250.0
        assert trends[0].change_percent == 40.0
        assert trends[0].direction == "increased"
        assert trends[0].significance == "high"
    
    def test_small_category_change_retains_exact_direction(self):
        """A low-significance change is not equality."""
        current = [{"category": "transport", "amount": {"amount": 102.0}}]
        previous = [{"category": "transport", "amount": {"amount": 100.0}}]
        
        trends = compute_category_trends(current, previous)
        
        assert trends[0].change_percent == 2.0
        assert trends[0].direction == "increased"
        assert trends[0].significance == "low"

    @pytest.mark.parametrize("current,previous,direction", [
        (660, 680, "decreased"),
        (680, 660, "increased"),
        (660, 660, "stable"),
        (660.001, 660.002, "stable"),
    ])
    def test_direction_matches_rounded_monetary_values(self, current, previous, direction):
        trends = compute_category_trends(
            [{"category": "food", "amount": {"amount": current}}],
            [{"category": "food", "amount": {"amount": previous}}],
        )
        assert trends[0].direction == direction
        assert trends[0].significance == "low"
    
    def test_category_trend_zero_previous(self):
        """Handle new categories (zero previous)."""
        current = [{"category": "shopping", "amount": {"amount": 50.0}}]
        previous = []
        
        trends = compute_category_trends(current, previous)
        
        assert trends[0].change_percent is None  # Percentage from zero is undefined.
        assert trends[0].direction == "increased"


class TestTemporalPatterns:
    """Test temporal pattern detection."""
    
    def test_weekend_spending_pattern(self):
        """Detect weekend vs weekday spending imbalance."""
        # 60% on weekends (Sat/Sun), 40% on weekdays
        transactions = [
            {"category": "food", "amount": {"amount": 50.0}, "occurred_on": "2024-08-03"},  # Saturday
            {"category": "food", "amount": {"amount": 60.0}, "occurred_on": "2024-08-04"},  # Sunday
            {"category": "food", "amount": {"amount": 55.0}, "occurred_on": "2024-08-10"},  # Saturday
            {"category": "food", "amount": {"amount": 65.0}, "occurred_on": "2024-08-11"},  # Sunday
            {"category": "food", "amount": {"amount": 10.0}, "occurred_on": "2024-08-05"},  # Monday
            {"category": "food", "amount": {"amount": 15.0}, "occurred_on": "2024-08-06"},  # Tuesday
        ]
        
        patterns = detect_temporal_patterns(transactions)
        
        # Should detect weekend concentration
        weekend_patterns = [p for p in patterns if p.pattern_type == "weekday_weekend"]
        assert len(weekend_patterns) > 0
        assert weekend_patterns[0].variance_percent > 15
    
    def test_no_temporal_pattern_balanced(self):
        """No pattern detected when spending is balanced."""
        transactions = [
            {"category": "food", "amount": {"amount": 50.0}, "occurred_on": "2024-08-03"},  # Saturday
            {"category": "food", "amount": {"amount": 50.0}, "occurred_on": "2024-08-05"},  # Monday
            {"category": "food", "amount": {"amount": 50.0}, "occurred_on": "2024-08-07"},  # Wednesday
        ]
        
        patterns = detect_temporal_patterns(transactions)
        
        # Should not detect significant patterns
        assert len(patterns) == 0


class TestAnomalyDetection:
    """Test statistical anomaly detection."""
    
    def test_z_score_anomaly_detection(self):
        """Detect statistical outliers using z-score."""
        # 5 months consistent, then 1 outlier
        transactions = [
            {"category": "dining", "amount": {"amount": 100.0}, "occurred_on": "2024-04-15"},
            {"category": "dining", "amount": {"amount": 105.0}, "occurred_on": "2024-05-15"},
            {"category": "dining", "amount": {"amount": 98.0}, "occurred_on": "2024-06-15"},
            {"category": "dining", "amount": {"amount": 102.0}, "occurred_on": "2024-07-15"},
            {"category": "dining", "amount": {"amount": 450.0}, "occurred_on": "2024-08-15"},  # Outlier
        ]
        
        anomalies = detect_anomalies(transactions, date(2024, 8, 1))
        
        assert len(anomalies) == 1
        assert anomalies[0].category == "dining"
        assert anomalies[0].amount == 450.0
        assert anomalies[0].z_score > 2.0
        assert anomalies[0].severity in ["medium", "high"]
    
    def test_no_anomalies_normal_data(self):
        """No false positives on consistent data."""
        transactions = [
            {"category": "food", "amount": {"amount": 100.0}, "occurred_on": "2024-04-15"},
            {"category": "food", "amount": {"amount": 105.0}, "occurred_on": "2024-05-15"},
            {"category": "food", "amount": {"amount": 98.0}, "occurred_on": "2024-06-15"},
        ]
        
        anomalies = detect_anomalies(transactions, date(2024, 6, 1))
        
        assert len(anomalies) == 0
    
    def test_insufficient_data_for_anomaly(self):
        """No anomaly detection with <3 months data."""
        transactions = [
            {"category": "food", "amount": {"amount": 100.0}, "occurred_on": "2024-08-01"},
            {"category": "food", "amount": {"amount": 120.0}, "occurred_on": "2024-08-15"},
        ]
        
        anomalies = detect_anomalies(transactions, date(2024, 8, 1))
        
        assert len(anomalies) == 0


class TestFullAnalysis:
    """Test complete spending analysis workflow."""
    
    def test_analyze_spending_patterns_complete(self):
        """Verify full analysis returns all expected fields."""
        transactions = [
            {"category": "food", "amount": {"amount": 100.0}, "occurred_on": "2024-07-15"},
            {"category": "food", "amount": {"amount": 120.0}, "occurred_on": "2024-08-01"},
            {"category": "transport", "amount": {"amount": 50.0}, "occurred_on": "2024-08-05"},
        ]
        
        result = analyze_spending_patterns(transactions, date(2024, 8, 1))
        
        assert "category_trends" in result
        assert "temporal_patterns" in result
        assert "anomalies" in result
        assert "data_quality" in result
        assert "months_analyzed" in result
        assert result["months_analyzed"] == 2
        assert result["data_quality"] == "limited"
    
    def test_analyze_spending_patterns_empty(self):
        """Verify graceful handling of empty transactions."""
        result = analyze_spending_patterns([], date(2024, 8, 1))
        
        assert result["data_quality"] == "insufficient"
        assert result["months_analyzed"] == 0
        assert result["category_trends"] == []
        assert result["anomalies"] == []
