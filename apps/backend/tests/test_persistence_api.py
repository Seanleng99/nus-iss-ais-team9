from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_profile_transactions_goals_and_snapshot_are_persisted() -> None:
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    profile_response = client.put(
        "/api/users/demo-user/profile",
        headers=headers,
        json={
            "monthly_income": {"currency": "SGD", "amount": 5000},
            "risk_tolerance": "moderate",
            "preferences": {"language": "en"},
        },
    )
    transaction_response = client.post(
        "/api/users/demo-user/transactions",
        headers=headers,
        json={
            "description": "Rent",
            "category": "housing",
            "amount": {"currency": "SGD", "amount": 1800},
            "occurred_on": "2026-08-01",
            "recurring": True,
        },
    )
    goal_response = client.post(
        "/api/users/demo-user/goals",
        headers=headers,
        json={
            "name": "Emergency fund",
            "target_amount": {"currency": "SGD", "amount": 12000},
            "current_amount": {"currency": "SGD", "amount": 3000},
            "target_months": 18,
        },
    )
    budget_response = client.put(
        "/api/users/demo-user/budget",
        headers=headers,
        json={
            "period_start": "2026-08-01",
            "currency": "SGD",
            "categories": [{"category": "housing", "limit_amount": 2000}],
        },
    )
    snapshot_response = client.get("/api/users/demo-user/snapshot", headers=headers)
    dashboard_response = client.get(
        "/api/users/demo-user/dashboard",
        headers=headers,
        params={"period_start": "2026-08-01"},
    )

    assert profile_response.status_code == 200
    assert transaction_response.status_code == 201
    assert goal_response.status_code == 201
    assert budget_response.status_code == 200
    assert snapshot_response.status_code == 200
    assert dashboard_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["monthly_income"]["amount"] == 5000
    assert snapshot["recurring_expenses"][0]["description"] == "Rent"
    assert snapshot["goals"][0]["name"] == "Emergency fund"
    dashboard = dashboard_response.json()
    assert dashboard["total_spent"] == 1800
    assert dashboard["available_balance"] == 3200
    assert dashboard["savings_rate_percent"] == 64
    assert dashboard["budget"]["total_remaining"] == 200
    assert dashboard["transaction_count"] == 1


def test_persistence_api_requires_service_key() -> None:
    response = TestClient(app).get("/api/users/demo-user/transactions")
    assert response.status_code == 401


def test_profiles_can_be_created_listed_and_not_overwritten() -> None:
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    payload = {
        "user_id": "alex-lee",
        "monthly_income": {"currency": "SGD", "amount": 6200},
        "risk_tolerance": "growth",
        "preferences": {"display_name": "Alex Lee"},
    }

    created = client.post("/api/profiles", headers=headers, json=payload)
    duplicate = client.post("/api/profiles", headers=headers, json=payload)
    profiles = client.get("/api/profiles", headers=headers)

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert profiles.status_code == 200
    assert profiles.json() == [
        {
            "user_id": "alex-lee",
            "display_name": "Alex Lee",
            "monthly_income": {"currency": "SGD", "amount": 6200.0},
            "risk_tolerance": "growth",
        }
    ]


def test_profile_creation_rejects_unsafe_profile_id() -> None:
    response = TestClient(app).post(
        "/api/profiles",
        headers={"X-API-Key": settings.api_key},
        json={"user_id": "invalid profile", "preferences": {"display_name": "Invalid"}},
    )

    assert response.status_code == 422
