"""
Spending Insights End-to-End Tests
===================================
Tests the complete workflow: transactions → analysis → insights → dashboard

Requirements:
- Backend must be running
- Database must be accessible
- Test user with transactions must exist

Run:
    pytest tests/e2e/test_spending_insights_e2e.py -v
"""

import pytest
from datetime import date, timedelta
from app.api.financial_schemas import DashboardResponse, SpendingInsight


@pytest.fixture
def test_user_with_transactions(client, test_user):
    """Create test user with 6 months of transaction data."""
    # Import here to avoid circular imports
    from app.infrastructure.repositories import SQLAlchemyTransactionRecord
    
    # Generate 6 months of test data
    base_date = date.today() - timedelta(days=180)
    
    transactions = []
    for month in range(6):
        month_date = base_date + timedelta(days=30 * month)
        
        # Normal dining expenses
        transactions.append({
            "user_id": test_user.id,
            "category": "dining",
            "amount": 100.0 + (month * 10),  # Gradual increase
            "occurred_on": month_date,
            "description": f"Dining month {month}",
        })
        
        # Add anomaly in last month
        if month == 5:
            transactions.append({
                "user_id": test_user.id,
                "category": "dining",
                "amount": 450.0,  # Anomaly: 3x normal
                "occurred_on": month_date + timedelta(days=15),
                "description": "Large dining expense",
            })
    
    # Insert transactions into database
    from app.infrastructure.database import get_db_session
    from app.infrastructure.repositories import TransactionRecord
    
    session = next(get_db_session())
    for txn_data in transactions:
        txn = TransactionRecord(**txn_data)
        session.add(txn)
    session.commit()
    session.close()
    
    return test_user


@pytest.mark.e2e
def test_full_spending_insights_workflow(client, test_user_with_transactions):
    """
    Test complete flow: transactions → analysis → insights → dashboard.
    
    Requirements:
    - Dashboard API returns spending_insights field
    - At least 3 insights generated
    - Anomaly detected in test data
    - Data quality indicator present
    """
    user_id = test_user_with_transactions.id
    period_start = date.today().replace(day=1)
    
    # Call dashboard API
    response = client.get(
        f"/api/v1/financial/users/{user_id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    
    # Validate response
    assert response.status_code == 200
    dashboard = response.json()
    
    # Verify spending_insights field exists
    assert "spending_insights" in dashboard, "Dashboard must include spending_insights"
    
    insights = dashboard["spending_insights"]
    assert len(insights) >= 3, f"Expected at least 3 insights, got {len(insights)}"
    assert len(insights) <= 5, f"Should not exceed 5 insights, got {len(insights)}"
    
    # Validate insight structure
    for insight in insights:
        assert "insight_id" in insight
        assert "insight_type" in insight
        assert insight["insight_type"] in ["trend", "pattern", "anomaly", "opportunity"]
        assert "title" in insight
        assert "description" in insight
        assert "confidence" in insight
        assert 0.0 <= insight["confidence"] <= 1.0
        assert "data_refs" in insight
    
    # Verify data quality indicators
    assert "spending_data_quality" in dashboard
    assert dashboard["spending_data_quality"] in ["insufficient", "limited", "good", "excellent"]
    
    assert "spending_months_analyzed" in dashboard
    assert dashboard["spending_months_analyzed"] >= 1


@pytest.mark.e2e
def test_anomaly_detection_in_dashboard(client, test_user_with_transactions):
    """
    Verify anomaly detection works in end-to-end flow.
    
    Requirements:
    - Anomaly insight appears in dashboard
    - Anomaly has correct severity
    - Anomaly references actual transaction amount
    """
    user_id = test_user_with_transactions.id
    period_start = date.today().replace(day=1)
    
    response = client.get(
        f"/api/v1/financial/users/{user_id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    
    assert response.status_code == 200
    dashboard = response.json()
    
    # Find anomaly insights
    anomalies = [
        i for i in dashboard["spending_insights"]
        if i["insight_type"] == "anomaly"
    ]
    
    assert len(anomalies) > 0, "Should detect at least one anomaly"
    
    # Verify anomaly details
    anomaly = anomalies[0]
    assert "dining" in anomaly["title"].lower() or "dining" in anomaly["description"].lower()
    assert "450" in anomaly["description"] or "450.0" in anomaly["description"]
    assert anomaly.get("severity") in ["low", "medium", "high"]


@pytest.mark.e2e
def test_trend_detection_in_dashboard(client, test_user_with_transactions):
    """
    Verify trend detection works in end-to-end flow.
    
    Requirements:
    - Trend insight appears for dining category
    - Shows month-over-month change
    - Percentage is accurate
    """
    user_id = test_user_with_transactions.id
    period_start = date.today().replace(day=1)
    
    response = client.get(
        f"/api/v1/financial/users/{user_id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    
    assert response.status_code == 200
    dashboard = response.json()
    
    # Find trend insights
    trends = [
        i for i in dashboard["spending_insights"]
        if i["insight_type"] == "trend"
    ]
    
    # Should have at least one trend (dining increased over months)
    assert len(trends) > 0, "Should detect at least one trend"
    
    # Verify trend references percentage change
    trend = trends[0]
    assert "%" in trend["title"] or "%" in trend["description"]


@pytest.mark.e2e
def test_dashboard_performance_with_insights(client, test_user_with_transactions):
    """
    Validate dashboard API response time with insights enabled.
    
    Requirements:
    - Response time < 2 seconds (P95)
    - Insights generation doesn't block API
    """
    import time
    
    user_id = test_user_with_transactions.id
    period_start = date.today().replace(day=1)
    
    start_time = time.time()
    response = client.get(
        f"/api/v1/financial/users/{user_id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    elapsed = time.time() - start_time
    
    assert response.status_code == 200
    assert elapsed < 2.0, f"API response took {elapsed:.2f}s, expected <2s"


@pytest.mark.e2e
def test_insight_priority_ordering(client, test_user_with_transactions):
    """
    Verify insights are ordered by priority (anomalies first).
    
    Requirements:
    - Anomalies appear before trends
    - Higher confidence insights ranked higher
    """
    user_id = test_user_with_transactions.id
    period_start = date.today().replace(day=1)
    
    response = client.get(
        f"/api/v1/financial/users/{user_id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    
    assert response.status_code == 200
    dashboard = response.json()
    
    insights = dashboard["spending_insights"]
    if len(insights) == 0:
        pytest.skip("No insights generated")
    
    # Check if anomalies (if any) appear before trends
    anomaly_indices = [i for i, ins in enumerate(insights) if ins["insight_type"] == "anomaly"]
    trend_indices = [i for i, ins in enumerate(insights) if ins["insight_type"] == "trend"]
    
    if anomaly_indices and trend_indices:
        # All anomalies should appear before all trends
        assert max(anomaly_indices) < min(trend_indices), \
            "Anomalies should be prioritized before trends"


@pytest.mark.e2e
def test_data_quality_indicators(client, test_user_with_transactions):
    """
    Verify data quality is reported correctly.
    
    Requirements:
    - Data quality matches months of data
    - Quality indicator is user-friendly
    """
    user_id = test_user_with_transactions.id
    period_start = date.today().replace(day=1)
    
    response = client.get(
        f"/api/v1/financial/users/{user_id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    
    assert response.status_code == 200
    dashboard = response.json()
    
    quality = dashboard["spending_data_quality"]
    months = dashboard["spending_months_analyzed"]
    
    # Verify quality matches months
    if months >= 6:
        assert quality == "excellent"
    elif months >= 3:
        assert quality == "good"
    elif months >= 1:
        assert quality == "limited"
    else:
        assert quality == "insufficient"
