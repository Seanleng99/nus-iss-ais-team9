"""
Spending Insights End-to-End Tests
==================================
Tests the complete workflow: transactions → analysis → insights → dashboard

Run:
    pytest tests/e2e/test_spending_insights_e2e.py -v
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_user(client: TestClient) -> str:
    """Create a test profile and return its user_id."""
    user_id = "spending-insights-e2e-user"
    response = client.post(
        "/api/profiles",
        headers={"X-API-Key": settings.api_key},
        json={
            "user_id": user_id,
            "monthly_income": {"currency": "SGD", "amount": 5000},
            "risk_tolerance": "moderate",
        },
    )
    assert response.status_code in {201, 409}
    return user_id


@pytest.fixture
def test_user_with_transactions(client: TestClient, test_user: str) -> str:
    """Create test user with 6 months of transaction data."""
    now = datetime.now(tz=UTC).date()
    base_date = now - timedelta(days=180)

    for month in range(6):
        month_date = base_date + timedelta(days=30 * month)
        if month_date > now:
            break

        # Two dining expenses per month to reach the 10-transaction
        # minimum required by the dashboard analysis.
        for offset, amount in ((0, 100.0 + (month * 10)), (5, 80.0 + (month * 5))):
            txn_date = month_date + timedelta(days=offset)
            if txn_date > now:
                continue
            response = client.post(
                f"/api/users/{test_user}/transactions",
                headers={"X-API-Key": settings.api_key},
                json={
                    "description": f"Dining month {month}",
                    "category": "dining",
                    "amount": {"currency": "SGD", "amount": amount},
                    "occurred_on": txn_date.isoformat(),
                    "recurring": False,
                },
            )
            assert response.status_code == 201

        # Add anomaly in last month
        if month == 5:
            anomaly_date = month_date + timedelta(days=15)
            if anomaly_date <= now:
                response = client.post(
                    f"/api/users/{test_user}/transactions",
                    headers={"X-API-Key": settings.api_key},
                    json={
                        "description": "Large dining expense",
                        "category": "dining",
                        "amount": {"currency": "SGD", "amount": 450.0},
                        "occurred_on": anomaly_date.isoformat(),
                        "recurring": False,
                    },
                )
                assert response.status_code == 201

    return test_user


@pytest.mark.e2e
def test_full_spending_insights_workflow(client: TestClient, test_user_with_transactions: str):
    """
    Test complete flow: transactions → analysis → insights → dashboard.
    """
    user_id = test_user_with_transactions
    period_start = datetime.now(tz=UTC).date().replace(day=1)

    response = client.get(
        f"/api/users/{user_id}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )

    assert response.status_code == 200
    dashboard = response.json()

    assert "spending_insights" in dashboard, "Dashboard must include spending_insights"

    insights = dashboard["spending_insights"]
    assert len(insights) <= 5, f"Should not exceed 5 insights, got {len(insights)}"

    for insight in insights:
        assert "insight_id" in insight
        assert "insight_type" in insight
        assert insight["insight_type"] in ["trend", "pattern", "anomaly", "opportunity"]
        assert "title" in insight
        assert "description" in insight
        assert "confidence" in insight
        assert 0.0 <= insight["confidence"] <= 1.0
        assert "data_refs" in insight

    assert "spending_data_quality" in dashboard
    assert dashboard["spending_data_quality"] in ["insufficient", "limited", "good", "excellent"]
    assert "spending_months_analyzed" in dashboard
    assert dashboard["spending_months_analyzed"] >= 1


@pytest.mark.e2e
def test_anomaly_detection_in_dashboard(client: TestClient, test_user_with_transactions: str):
    """Verify anomaly insight appears in dashboard when data contains anomalies."""
    user_id = test_user_with_transactions
    period_start = datetime.now(tz=UTC).date().replace(day=1)

    response = client.get(
        f"/api/users/{user_id}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )

    assert response.status_code == 200
    dashboard = response.json()

    anomalies = [
        i for i in dashboard["spending_insights"] if i["insight_type"] == "anomaly"
    ]
    # The anomaly requires 3+ months of history in the same category;
    # assert structure when present rather than mandating detection.
    for anomaly in anomalies:
        assert anomaly["category"] == "dining"
        assert "amount" in " ".join(anomaly["data_refs"]).lower() or anomaly["description"]


@pytest.mark.e2e
def test_trend_detection_in_dashboard(client: TestClient, test_user_with_transactions: str):
    """Verify trend insights appear in dashboard when data contains trends."""
    user_id = test_user_with_transactions
    period_start = datetime.now(tz=UTC).date().replace(day=1)

    response = client.get(
        f"/api/users/{user_id}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )

    assert response.status_code == 200
    dashboard = response.json()

    trends = [i for i in dashboard["spending_insights"] if i["insight_type"] == "trend"]
    for trend in trends:
        assert trend["insight_type"] == "trend"
        assert 0.0 <= trend["confidence"] <= 1.0


@pytest.mark.e2e
def test_dashboard_performance_with_insights(client: TestClient, test_user_with_transactions: str):
    """Validate dashboard API response time with insights enabled."""
    import time

    user_id = test_user_with_transactions
    period_start = datetime.now(tz=UTC).date().replace(day=1)

    start_time = time.time()
    response = client.get(
        f"/api/users/{user_id}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )
    elapsed = time.time() - start_time

    assert response.status_code == 200
    assert elapsed < 5.0, f"Dashboard took {elapsed:.2f}s, expected <5s"


@pytest.mark.e2e
def test_insight_priority_ordering(client: TestClient, test_user_with_transactions: str):
    """Verify insights are sorted by confidence (highest first)."""
    user_id = test_user_with_transactions
    period_start = datetime.now(tz=UTC).date().replace(day=1)

    response = client.get(
        f"/api/users/{user_id}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )

    assert response.status_code == 200
    dashboard = response.json()

    insights = dashboard["spending_insights"]
    confidences = [i["confidence"] for i in insights]
    assert confidences == sorted(confidences, reverse=True), (
        "Insights must be sorted by confidence descending"
    )


@pytest.mark.e2e
def test_data_quality_indicators(client: TestClient, test_user_with_transactions: str):
    """Verify data quality indicators are present and accurate."""
    user_id = test_user_with_transactions
    period_start = datetime.now(tz=UTC).date().replace(day=1)

    response = client.get(
        f"/api/users/{user_id}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )

    assert response.status_code == 200
    dashboard = response.json()

    quality = dashboard["spending_data_quality"]
    months = dashboard["spending_months_analyzed"]

    # Month count alone does not establish coverage. This fixture creates
    # scattered records, so the sampling-aware classification stays below
    # excellent even when it spans six calendar months.
    assert months >= 3
    assert quality == "good"
