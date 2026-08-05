import json
from datetime import date

import httpx

from client import BackendClient, build_request


def test_build_request_uses_backend_owned_snapshot() -> None:
    payload = build_request("  demo-user  ", "  Create a budget  ")
    assert payload["user_id"] == "demo-user"
    assert payload["message"] == "Create a budget"
    assert payload["session_id"]
    assert "snapshot" not in payload


def test_client_sends_service_key_and_period() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[])

    client = BackendClient(
        base_url="http://backend.test",
        api_key="test-service-key",
        transport=httpx.MockTransport(handler),
    )
    response = client.list_transactions("demo-user", date(2026, 8, 1))

    assert response == []
    assert captured[0].headers["X-API-Key"] == "test-service-key"
    assert captured[0].url.path == "/api/users/demo-user/transactions"
    assert captured[0].url.params["period_start"] == "2026-08-01"


def test_client_supports_not_found_profile() -> None:
    client = BackendClient(
        base_url="http://backend.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(404, json={})),
    )
    assert client.get_profile("missing-user") is None


def test_client_updates_budget_and_coaching_routes() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/budget"):
            return httpx.Response(200, json={"period_start": "2026-08-01"})
        return httpx.Response(200, json={"answer": "guidance"})

    client = BackendClient(
        base_url="http://backend.test",
        transport=httpx.MockTransport(handler),
    )
    budget_payload = {
        "period_start": "2026-08-01",
        "currency": "SGD",
        "categories": [{"category": "housing", "limit_amount": 1800}],
    }
    client.save_budget("demo-user", budget_payload)
    response = client.ask_coach(build_request("demo-user", "Review my budget"))

    assert response == {"answer": "guidance"}
    assert captured[0].method == "PUT"
    assert json.loads(captured[0].content) == budget_payload
    assert captured[1].url.path == "/api/coach"
    assert "snapshot" not in json.loads(captured[1].content)
