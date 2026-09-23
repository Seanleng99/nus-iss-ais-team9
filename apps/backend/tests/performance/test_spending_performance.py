"""
Spending Analysis Performance Tests
===================================
Validates performance SLOs for spending analysis.

Run:
    pytest tests/performance/test_spending_performance.py -v -m performance
"""

import random
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.infrastructure.repositories import TransactionRecord
from app.main import app
from app.services.spending_analyzer import analyze_spending_patterns


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_user(db_session_factory) -> str:
    """Create a test profile and return its user_id."""
    from app.infrastructure.models import FinancialProfileRecord, UserRecord

    user_id = "spending-perf-user"
    with db_session_factory() as session:
        session.add(UserRecord(id=user_id))
        session.add(FinancialProfileRecord(user_id=user_id, currency="SGD"))
        session.commit()
    return user_id


def generate_test_transactions(session, user_id: str, count: int = 500, months: int = 6) -> int:
    """Generate realistic test transaction data."""
    categories = ["food", "transport", "shopping", "entertainment", "utilities"]
    base_date = datetime.now(tz=UTC).date() - timedelta(days=months * 30)

    transactions = []
    for i in range(count):
        txn_date = base_date + timedelta(days=random.randint(0, months * 30))
        category = random.choice(categories)
        amount = random.uniform(20, 200)

        # Add some anomalies (5% of transactions)
        if random.random() < 0.05:
            amount *= random.uniform(3, 5)

        transactions.append(
            TransactionRecord(
                user_id=user_id,
                category=category,
                amount=amount,
                occurred_on=txn_date,
                description=f"Test transaction {i}",
            )
        )

    session.bulk_save_objects(transactions)
    session.commit()
    return len(transactions)


@pytest.mark.performance
def test_spending_analysis_latency(client: TestClient, db_session_factory, test_user: str):
    """
    Validate spending analysis completes in <5 seconds.

    SLO: P95 < 5 seconds for 500 transactions over 6 months
    """
    with db_session_factory() as session:
        generate_test_transactions(session, test_user, count=500, months=6)

    period_start = datetime.now(tz=UTC).date().replace(day=1)

    start_time = time.time()
    response = client.get(
        f"/api/users/{test_user}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )
    elapsed = time.time() - start_time

    assert response.status_code == 200
    assert elapsed < 5.0, f"Analysis took {elapsed:.2f}s, expected <5s"
    print(f"\n✅ Performance: Analysis completed in {elapsed:.2f}s (SLO: <5s)")


@pytest.mark.performance
def test_direct_analysis_latency():
    """Validate direct analyzer call completes quickly."""
    base = datetime.now(tz=UTC).date().replace(day=1)
    transactions = []
    for month in range(6):
        for i in range(100):
            transactions.append(
                {
                    "category": random.choice(["food", "transport", "shopping"]),
                    "amount": {"currency": "SGD", "amount": random.uniform(10, 150)},
                    "occurred_on": (
                        base - timedelta(days=30 * month + random.randint(0, 27))
                    ).isoformat(),
                }
            )

    start = time.time()
    result = analyze_spending_patterns(transactions, base)
    elapsed = time.time() - start

    assert result["data_quality"] in ["insufficient", "limited", "good", "excellent"]
    assert elapsed < 2.0, f"Direct analysis took {elapsed:.3f}s, expected <2s"
    print(f"\n✅ Performance: Direct analysis {elapsed * 1000:.1f}ms for 600 transactions")


@pytest.mark.performance
def test_dashboard_api_response_time(client: TestClient, db_session_factory, test_user: str):
    """
    Validate dashboard API response time <2 seconds.
    """
    with db_session_factory() as session:
        generate_test_transactions(session, test_user, count=200, months=6)

    period_start = datetime.now(tz=UTC).date().replace(day=1)

    start_time = time.time()
    response = client.get(
        f"/api/users/{test_user}/dashboard",
        headers={"X-API-Key": settings.api_key},
        params={"period_start": period_start.isoformat()},
    )
    elapsed = time.time() - start_time

    assert response.status_code == 200
    assert elapsed < 2.0, f"Dashboard took {elapsed:.2f}s, expected <2s"
    print(f"\n✅ Performance: Dashboard response {elapsed:.2f}s (SLO: <2s)")


@pytest.mark.performance
def test_repeated_dashboard_requests(client: TestClient, db_session_factory, test_user: str):
    """Test dashboard stability and timing across repeated requests.

    Uses sequential requests because the isolated in-memory SQLite test
    database does not support cross-thread connections; production Postgres
    handles concurrent load natively.
    """
    with db_session_factory() as session:
        generate_test_transactions(session, test_user, count=100, months=6)

    period_start = datetime.now(tz=UTC).date().replace(day=1)

    times = []
    for _ in range(10):
        start = time.time()
        response = client.get(
            f"/api/users/{test_user}/dashboard",
            headers={"X-API-Key": settings.api_key},
            params={"period_start": period_start.isoformat()},
        )
        assert response.status_code == 200
        times.append(time.time() - start)

    avg_time = sum(times) / len(times)
    assert avg_time < 2.0, f"Average response {avg_time:.2f}s, expected <2s"
    print(f"\n✅ Performance: 10 repeated requests, avg {avg_time:.2f}s")


@pytest.mark.performance
def test_memory_usage_with_large_dataset(db_session_factory, test_user: str):
    """
    Test memory efficiency with large transaction datasets.

    SLO: <100MB memory for 1000 transactions
    """
    import tracemalloc

    with db_session_factory() as session:
        generate_test_transactions(session, test_user, count=1000, months=12)

    tracemalloc.start()

    base = datetime.now(tz=UTC).date().replace(day=1)
    transactions = [
        {
            "category": random.choice(["food", "transport", "shopping"]),
            "amount": {"currency": "SGD", "amount": random.uniform(10, 150)},
            "occurred_on": (base - timedelta(days=random.randint(0, 360))).isoformat(),
        }
        for _ in range(1000)
    ]
    analyze_spending_patterns(transactions, base)

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak / 1024 / 1024
    assert peak_mb < 100, f"Peak memory {peak_mb:.1f}MB, expected <100MB"
    print(f"\n✅ Performance: Peak memory usage {peak_mb:.1f}MB (SLO: <100MB)")
