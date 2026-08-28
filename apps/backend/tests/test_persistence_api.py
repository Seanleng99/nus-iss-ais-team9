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


def test_profile_deletion_removes_all_user_data() -> None:
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    profile = {
        "user_id": "delete-user",
        "preferences": {"display_name": "Delete User"},
    }

    assert client.post("/api/profiles", headers=headers, json=profile).status_code == 201
    assert client.post(
        "/api/users/delete-user/transactions",
        headers=headers,
        json={
            "description": "Rent",
            "category": "housing",
            "amount": {"currency": "SGD", "amount": 1800},
            "occurred_on": "2026-08-01",
            "recurring": True,
        },
    ).status_code == 201
    assert client.post(
        "/api/users/delete-user/goals",
        headers=headers,
        json={
            "name": "Emergency fund",
            "target_amount": {"currency": "SGD", "amount": 12000},
            "current_amount": {"currency": "SGD", "amount": 1000},
            "target_months": 12,
        },
    ).status_code == 201
    assert client.put(
        "/api/users/delete-user/budget",
        headers=headers,
        json={
            "period_start": "2026-08-01",
            "currency": "SGD",
            "categories": [{"category": "housing", "limit_amount": 2000}],
        },
    ).status_code == 200
    assert client.put(
        "/api/users/delete-user/fairness-consent",
        headers=headers,
        json={"granted": True},
    ).status_code == 200
    assert client.put(
        "/api/users/delete-user/demographics",
        headers=headers,
        json={"age_band": "26-30", "race_ethnicity": ["Malay"]},
    ).status_code == 200

    deleted = client.delete("/api/users/delete-user/profile", headers=headers)
    deleted_again = client.delete("/api/users/delete-user/profile", headers=headers)

    assert deleted.status_code == 204
    assert deleted_again.status_code == 404
    assert client.get("/api/users/delete-user/profile", headers=headers).status_code == 404
    assert client.get("/api/profiles", headers=headers).json() == []

    assert client.post("/api/profiles", headers=headers, json=profile).status_code == 201
    assert client.get(
        "/api/users/delete-user/transactions",
        headers=headers,
        params={"period_start": "2026-08-01"},
    ).json() == []
    assert client.get("/api/users/delete-user/goals", headers=headers).json() == []
    assert client.get(
        "/api/users/delete-user/budget",
        headers=headers,
        params={"period_start": "2026-08-01"},
    ).status_code == 404
    fairness = client.get(
        "/api/users/delete-user/fairness-profile", headers=headers
    ).json()
    assert fairness["consent"]["granted"] is False
    assert fairness["demographics"] is None


def test_profile_creation_rejects_unsafe_profile_id() -> None:
    response = TestClient(app).post(
        "/api/profiles",
        headers={"X-API-Key": settings.api_key},
        json={"user_id": "invalid profile", "preferences": {"display_name": "Invalid"}},
    )

    assert response.status_code == 422


def test_fairness_data_requires_consent_is_isolated_and_is_deleted_on_withdrawal() -> None:
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    profile_payload = {
        "user_id": "fairness-user",
        "monthly_income": {"currency": "SGD", "amount": 5200},
        "risk_tolerance": "moderate",
        "employment_status": "employed",
        "occupation_category": "education",
        "income_frequency": "monthly",
        "income_stability": "stable",
        "household_size": 3,
        "dependants": 1,
        "housing_status": "renting",
        "financial_literacy": "beginner",
        "preferred_language": "English",
        "accessibility_preferences": ["plain language"],
        "preferences": {"display_name": "Fairness User"},
    }
    demographic_payload = {
        "age_band": "26-30",
        "gender_identity": "Woman",
        "race_ethnicity": ["Malay"],
        "nationality_residency": "Singapore citizen",
        "disability_status": "Prefer not to say",
        "marital_status": "Single",
        "residential_region": "East",
    }

    assert client.post("/api/profiles", headers=headers, json=profile_payload).status_code == 201
    denied = client.put(
        "/api/users/fairness-user/demographics",
        headers=headers,
        json=demographic_payload,
    )
    consent = client.put(
        "/api/users/fairness-user/fairness-consent",
        headers=headers,
        json={"granted": True},
    )
    demographics = client.put(
        "/api/users/fairness-user/demographics",
        headers=headers,
        json=demographic_payload,
    )
    fairness_profile = client.get(
        "/api/users/fairness-user/fairness-profile", headers=headers
    )
    normal_profile = client.get("/api/users/fairness-user/profile", headers=headers)
    snapshot = client.get("/api/users/fairness-user/snapshot", headers=headers)

    assert denied.status_code == 403
    assert consent.status_code == 200
    assert consent.json()["granted"] is True
    assert consent.json()["granted_at"] is not None
    assert demographics.status_code == 200
    assert fairness_profile.json()["demographics"] == {
        "user_id": "fairness-user",
        **demographic_payload,
    }
    assert "age_band" not in normal_profile.json()
    snapshot_json = snapshot.json()
    assert snapshot_json["preferences"]["employment_status"] == "employed"
    assert snapshot_json["preferences"]["accessibility_preferences"] == [
        "plain language"
    ]
    assert "display_name" not in snapshot_json["preferences"]
    assert not set(demographic_payload).intersection(snapshot_json["preferences"])

    withdrawal = client.put(
        "/api/users/fairness-user/fairness-consent",
        headers=headers,
        json={"granted": False},
    )
    after_withdrawal = client.get(
        "/api/users/fairness-user/fairness-profile", headers=headers
    )
    assert withdrawal.json()["granted"] is False
    assert withdrawal.json()["withdrawn_at"] is not None
    assert after_withdrawal.json()["demographics"] is None


def test_profile_rejects_dependants_above_household_size() -> None:
    response = TestClient(app).post(
        "/api/profiles",
        headers={"X-API-Key": settings.api_key},
        json={
            "user_id": "invalid-household",
            "household_size": 1,
            "dependants": 2,
        },
    )

    assert response.status_code == 422


def test_chat_sessions_are_profile_scoped_and_manageable() -> None:
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    for user_id in ("chat-alex", "chat-sam"):
        assert client.post(
            "/api/profiles",
            headers=headers,
            json={"user_id": user_id},
        ).status_code == 201

    created = client.post(
        "/api/users/chat-alex/chat-sessions",
        headers=headers,
        json={"id": "chat-1", "title": "Budget review"},
    )
    assert created.status_code == 201
    assert created.json()["messages"] == []
    assert client.get(
        "/api/users/chat-sam/chat-sessions/chat-1", headers=headers
    ).status_code == 404
    assert client.post(
        "/api/users/chat-sam/chat-sessions",
        headers=headers,
        json={"id": "chat-1", "title": "Colliding conversation"},
    ).status_code == 409

    renamed = client.patch(
        "/api/users/chat-alex/chat-sessions/chat-1",
        headers=headers,
        json={"title": "Monthly budget"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Monthly budget"
    assert client.get(
        "/api/users/chat-alex/chat-sessions", headers=headers
    ).json()[0]["message_count"] == 0

    assert client.delete(
        "/api/users/chat-alex/chat-sessions/chat-1", headers=headers
    ).status_code == 204
    assert client.get(
        "/api/users/chat-alex/chat-sessions", headers=headers
    ).json() == []
    assert client.post(
        "/api/users/chat-alex/chat-sessions",
        headers=headers,
        json={"id": "chat-2", "title": "Profile remains"},
    ).status_code == 201
