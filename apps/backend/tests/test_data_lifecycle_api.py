from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.data_lifecycle import DATA_LIFECYCLE_POLICY_VERSION
from app.main import app


def test_owner_can_review_consent_export_and_delete_all_workspace_data() -> None:
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    user_id = "lifecycle-user"

    assert client.put(
        f"/api/users/{user_id}/profile",
        headers=headers,
        json={
            "monthly_income": {"currency": "SGD", "amount": 5000},
            "preferences": {"display_name": "Lifecycle User"},
        },
    ).status_code == 200
    assert client.post(
        f"/api/users/{user_id}/transactions",
        headers=headers,
        json={
            "description": "Rent",
            "category": "housing",
            "amount": {"currency": "SGD", "amount": 1800},
            "occurred_on": "2026-08-01",
        },
    ).status_code == 201
    assert client.post(
        f"/api/users/{user_id}/chat-sessions",
        headers=headers,
        json={"id": "lifecycle-chat", "title": "Data rights"},
    ).status_code == 201

    lifecycle = client.get(
        f"/api/users/{user_id}/data-lifecycle", headers=headers
    )
    assert lifecycle.status_code == 200
    assert lifecycle.json()["policy_version"] == DATA_LIFECYCLE_POLICY_VERSION
    assert lifecycle.json()["retention"] == {
        "authenticated_financial_workspace": "until_owner_deletion",
        "orchestration_traces_days": 30,
        "chat_history_days": 90,
        "synthetic_automation_users_days": 30,
    }
    assert lifecycle.json()["durable_memory"] == {
        "purpose": "durable_agent_memory",
        "consent_version": "1.0",
        "granted": False,
        "granted_at": None,
        "withdrawn_at": None,
        "feature_enabled": False,
    }

    consent = client.put(
        f"/api/users/{user_id}/memory-consent",
        headers=headers,
        json={"granted": True},
    )
    assert consent.status_code == 200
    assert consent.json()["granted"] is True
    assert consent.json()["feature_enabled"] is False

    exported = client.get(f"/api/users/{user_id}/data-export", headers=headers)
    assert exported.status_code == 200
    payload = exported.json()
    assert payload["schema_version"] == 1
    assert payload["policy_version"] == DATA_LIFECYCLE_POLICY_VERSION
    assert payload["data"]["profile"]["monthly_income"]["amount"] == 5000
    assert payload["data"]["transactions"][0]["description"] == "Rent"
    assert payload["data"]["chat_sessions"][0]["id"] == "lifecycle-chat"
    assert payload["data"]["consents"][0]["purpose"] == "durable_agent_memory"
    assert "owner_issuer" not in exported.text
    assert "owner_subject" not in exported.text

    stale_policy = client.request(
        "DELETE",
        f"/api/users/{user_id}/data",
        headers=headers,
        json={"confirm_user_id": user_id, "policy_version": "stale-policy"},
    )
    assert stale_policy.status_code == 409
    assert client.get(f"/api/users/{user_id}/profile", headers=headers).status_code == 200

    deleted = client.request(
        "DELETE",
        f"/api/users/{user_id}/data",
        headers=headers,
        json={
            "confirm_user_id": user_id,
            "policy_version": DATA_LIFECYCLE_POLICY_VERSION,
        },
    )
    assert deleted.status_code == 200
    receipt = deleted.json()
    assert receipt["policy_version"] == DATA_LIFECYCLE_POLICY_VERSION
    assert receipt["deleted_counts"]["profiles"] == 1
    assert receipt["deleted_counts"]["transactions"] == 1
    assert receipt["deleted_counts"]["chat_sessions"] == 1
    assert receipt["deleted_counts"]["consents"] == 1
    assert client.get(f"/api/users/{user_id}/profile", headers=headers).status_code == 404


def test_data_deletion_requires_exact_user_confirmation() -> None:
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    assert client.put(
        "/api/users/confirmation-user/profile", headers=headers, json={}
    ).status_code == 200

    response = client.request(
        "DELETE",
        "/api/users/confirmation-user/data",
        headers=headers,
        json={
            "confirm_user_id": "someone-else",
            "policy_version": DATA_LIFECYCLE_POLICY_VERSION,
        },
    )

    assert response.status_code == 422
    assert client.get(
        "/api/users/confirmation-user/profile", headers=headers
    ).status_code == 200
