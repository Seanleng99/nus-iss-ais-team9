"""
Spending Analysis Performance Tests
====================================
Validates performance SLOs for spending analysis.

Requirements:
- Backend must be running
- Test data generator available
- Performance monitoring enabled

Run:
    pytest tests/performance/test_spending_performance.py -v -m performance
"""

import pytest
import time
from datetime import date, timedelta
from app.infrastructure.repositories import TransactionRecord


def generate_test_transactions(session, user_id: str, count: int = 500, months: int = 6):
    """Generate realistic test transaction data."""
    import random
    from datetime import timedelta
    
    categories = ["food", "transport", "shopping", "entertainment", "utilities"]
    base_date = date.today() - timedelta(days=months * 30)
    
    transactions = []
    for i in range(count):
        txn_date = base_date + timedelta(days=random.randint(0, months * 30))
        category = random.choice(categories)
        amount = random.uniform(20, 200)
        
        # Add some anomalies (5% of transactions)
        if random.random() < 0.05:
            amount *= random.uniform(3, 5)
        
        transactions.append(TransactionRecord(
            user_id=user_id,
            category=category,
            amount=amount,
            occurred_on=txn_date,
            description=f"Test transaction {i}",
        ))
    
    # Bulk insert
    session.bulk_save_objects(transactions)
    session.commit()
    
    return len(transactions)


@pytest.mark.performance
def test_spending_analysis_latency(client, test_user):
    """
    Validate spending analysis completes in <5 seconds.
    
    SLO: P95 < 5 seconds for 500 transactions over 6 months
    """
    from app.infrastructure.database import get_db_session
    
    # Generate 500 transactions
    session = next(get_db_session())
    generate_test_transactions(session, test_user.id, count=500, months=6)
    session.close()
    
    # Measure analysis time
    period_start = date.today().replace(day=1)
    
    start_time = time.time()
    response = client.get(
        f"/api/v1/financial/users/{test_user.id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    elapsed = time.time() - start_time
    
    assert response.status_code == 200
    assert elapsed < 5.0, f"Analysis took {elapsed:.2f}s, expected <5s"
    
    # Log performance metric
    print(f"\n✅ Performance: Analysis completed in {elapsed:.2f}s (SLO: <5s)")


@pytest.mark.performance
def test_dashboard_api_response_time(client, test_user):
    """
    Validate dashboard API response time <2 seconds.
    
    SLO: P95 < 2 seconds including insight generation
    """
    from app.infrastructure.database import get_db_session
    
    # Generate test data
    session = next(get_db_session())
    generate_test_transactions(session, test_user.id, count=300, months=4)
    session.close()
    
    period_start = date.today().replace(day=1)
    
    # Measure API response time
    start_time = time.time()
    response = client.get(
        f"/api/v1/financial/users/{test_user.id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    elapsed = time.time() - start_time
    
    assert response.status_code == 200
    assert elapsed < 2.0, f"API took {elapsed:.2f}s, expected <2s"
    
    # Log performance metric
    print(f"\n✅ Performance: API response in {elapsed:.2f}s (SLO: <2s)")


@pytest.mark.performance
def test_statistical_analysis_performance():
    """
    Test statistical analysis layer performance in isolation.
    
    SLO: <1 second for 500 transactions
    """
    from app.services.spending_analyzer import analyze_spending_patterns
    import random
    
    # Generate 500 test transactions
    transactions = []
    base_date = date.today() - timedelta(days=180)
    
    for i in range(500):
        txn_date = base_date + timedelta(days=random.randint(0, 180))
        transactions.append({
            "category": random.choice(["food", "transport", "shopping"]),
            "amount": {"amount": random.uniform(20, 200)},
            "occurred_on": txn_date.isoformat(),
        })
    
    # Measure analysis time
    start_time = time.time()
    result = analyze_spending_patterns(transactions, date.today().replace(day=1))
    elapsed = time.time() - start_time
    
    assert elapsed < 1.0, f"Statistical analysis took {elapsed:.2f}s, expected <1s"
    assert "category_trends" in result
    assert "anomalies" in result
    
    print(f"\n✅ Performance: Statistical analysis in {elapsed:.3f}s (SLO: <1s)")


@pytest.mark.performance
def test_insight_generation_performance():
    """
    Test insight generation performance.
    
    SLO: <2 seconds for LLM interpretation
    """
    from app.services.spending_analyzer import _generate_insights
    import time
    
    # Prepare test analysis result
    analysis_result = {
        "category_trends": [
            {
                "category": "food",
                "current_amount": 400.0,
                "previous_amount": 300.0,
                "change_percent": 33.3,
                "direction": "increased",
                "significance": "high",
            }
            for _ in range(5)
        ],
        "anomalies": [
            {
                "category": "dining",
                "amount": 450.0,
                "expected_amount": 110.0,
                "deviation_percent": 309.0,
                "z_score": 3.5,
                "severity": "high",
                "occurred_on": date.today().isoformat(),
            }
        ],
        "temporal_patterns": [
            {
                "pattern_type": "weekday_weekend",
                "description": "Weekend spending concentration",
                "variance_percent": 45.0,
                "confidence": 0.85,
            }
        ],
        "data_quality": "good",
        "months_analyzed": 6,
    }
    
    # Measure insight generation time
    start_time = time.time()
    insights = _generate_insights(analysis_result)
    elapsed = time.time() - start_time
    
    assert elapsed < 2.0, f"Insight generation took {elapsed:.2f}s, expected <2s"
    assert len(insights) > 0
    
    print(f"\n✅ Performance: Insight generation in {elapsed:.3f}s (SLO: <2s)")


@pytest.mark.performance
def test_concurrent_dashboard_requests(client, test_user):
    """
    Test dashboard performance under concurrent load.
    
    SLO: <3 seconds average for 10 concurrent requests
    """
    import concurrent.futures
    from app.infrastructure.database import get_db_session
    
    # Generate test data
    session = next(get_db_session())
    generate_test_transactions(session, test_user.id, count=200, months=3)
    session.close()
    
    period_start = date.today().replace(day=1)
    
    def make_request():
        start = time.time()
        response = client.get(
            f"/api/v1/financial/users/{test_user.id}/dashboard",
            params={"period_start": period_start.isoformat()},
        )
        elapsed = time.time() - start
        return response.status_code, elapsed
    
    # Make 10 concurrent requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request) for _ in range(10)]
        results = [f.result() for f in futures]
    
    # Validate results
    status_codes = [r[0] for r in results]
    times = [r[1] for r in results]
    
    assert all(code == 200 for code in status_codes), "All requests should succeed"
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    
    assert avg_time < 3.0, f"Average response time {avg_time:.2f}s, expected <3s"
    assert max_time < 5.0, f"Max response time {max_time:.2f}s, expected <5s"
    
    print(f"\n✅ Performance: Concurrent requests - avg {avg_time:.2f}s, max {max_time:.2f}s")


@pytest.mark.performance
def test_memory_usage_with_large_dataset(client, test_user):
    """
    Test memory efficiency with large transaction datasets.
    
    SLO: <100MB memory for 1000 transactions
    """
    import tracemalloc
    from app.infrastructure.database import get_db_session
    
    # Start memory tracking
    tracemalloc.start()
    
    # Generate 1000 transactions
    session = next(get_db_session())
    generate_test_transactions(session, test_user.id, count=1000, months=12)
    session.close()
    
    # Call dashboard
    period_start = date.today().replace(day=1)
    response = client.get(
        f"/api/v1/financial/users/{test_user.id}/dashboard",
        params={"period_start": period_start.isoformat()},
    )
    
    # Check memory usage
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    peak_mb = peak / 1024 / 1024
    assert peak_mb < 100, f"Peak memory {peak_mb:.1f}MB, expected <100MB"
    
    print(f"\n✅ Performance: Peak memory usage {peak_mb:.1f}MB (SLO: <100MB)")
