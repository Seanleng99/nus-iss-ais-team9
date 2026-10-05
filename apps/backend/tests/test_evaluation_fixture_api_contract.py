from uuid import uuid4

from coach_math.calendar import financial_today
from fastapi.testclient import TestClient
from infra.scripts import live_evaluation

from app.core.config import settings
from app.main import app


def test_harness_fixture_seeding_and_full_cleanup_use_real_owned_api_contract(monkeypatch):
    headers = {"X-API-Key": settings.api_key}
    actor = "live-evaluation-" + uuid4().hex
    today = financial_today().isoformat()
    with TestClient(app) as client:
        def owned(url, _key, method, payload, _timeout):
            path = live_evaluation.urllib.parse.urlparse(url).path
            response = client.request(method, path, headers=headers, json=payload)
            assert response.status_code < 300, response.text
            return response.json() if response.content else {}
        monkeypatch.setattr(live_evaluation, "_owned_api_request_json", owned)
        counts = live_evaluation.seed_case_snapshot("http://testserver/api/coach", settings.api_key,
            actor, {"monthly_income": {"amount": 4000}, "preferences": {"preferred_language": "English"},
                "recent_transactions": [{"description": "Meal", "category": "food", "amount": {"amount": 10}, "occurred_on": today}],
                "goals": [{"name": "Reserve", "target_amount": {"amount": 100}, "target_months": 2}]}, 1)
        assert counts == {"transactions": 1, "goals": 1}
        snapshot = client.get(f"/api/users/{actor}/snapshot", headers=headers).json()
        assert snapshot["monthly_income"]["amount"] == 4000
        assert snapshot["recent_transactions"][0]["amount"]["amount"] == 10
        assert snapshot["goals"][0]["name"] == "Reserve"
        assert live_evaluation.cleanup_user_data("http://testserver/api/coach", settings.api_key, actor, 1)
        assert client.get(f"/api/users/{actor}/profile", headers=headers).status_code == 404
        assert client.get(f"/api/users/{actor}/transactions", headers=headers).json() == []
        assert client.get(f"/api/users/{actor}/goals", headers=headers).json() == []
