from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app
from app.services.recurring_forecast import parse_recurring_forecast_query

TODAY = date(2026, 9, 25)

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class StubAIServiceClient:
    last_request: CoachRequest | None = None

    async def coach(self, request: CoachRequest) -> CoachResponse:
        StubAIServiceClient.last_request = request
        forecast = "recurring" in request.message.lower() and "what is a" not in request.message.lower() and not request.message.lower().startswith("explain")
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["spending"],
            answer="Stub guidance",
            agent_results=[{"agent": "spending", "summary": "Proposed forecast lookup", "data": {
                "spending_draft": {"action": "forecast", "query_start": "2026-10-01", "query_end": "2026-10-31"}}}]
                if forecast else [],
            disclaimers=[],
            audit={"source": "stub"},
        )


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.transaction_capture as capture

    monkeypatch.setattr(capture, "_today", lambda: TODAY)


@pytest.fixture
def stub_ai() -> Iterator[type[StubAIServiceClient]]:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    StubAIServiceClient.last_request = None
    try:
        yield StubAIServiceClient
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


def post_coach(user_id: str, message: str, session_id: str = "rf-s1") -> dict:
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": user_id, "session_id": session_id, "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_transaction(
    user_id: str,
    description: str,
    category: str,
    amount: float,
    occurred_on: str,
    recurring: bool = False,
) -> None:
    response = client.post(
        f"/api/users/{user_id}/transactions",
        headers=HEADERS,
        json={
            "description": description,
            "category": category,
            "amount": {"currency": "SGD", "amount": amount},
            "occurred_on": occurred_on,
            "recurring": recurring,
        },
    )
    assert response.status_code == 201, response.text


def test_add_subscription_request_is_not_forecast_intent() -> None:
    assert not parse_recurring_forecast_query(
        "can you help me add my Spotify monthly subscription that costs 10.90"
    )
    assert parse_recurring_forecast_query(
        "estimate my upcoming spendings based on my recurring spendings"
    )


def test_recurring_forecast_preserves_unknown_legacy_records_without_inventing_cadence(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("rf-u1", "Netflix subscription", "entertainment", 15.0, "2026-07-20", True)
    add_transaction("rf-u1", "Netflix subscription", "entertainment", 18.0, "2026-09-01", True)
    add_transaction("rf-u1", "Electric bill", "utilities", 130.0, "2026-08-20", True)
    add_transaction("rf-u1", "Kopi", "food", 2.0, "2026-09-24")
    body = post_coach(
        "rf-u1",
        "would you be able to estimate my upcoming spendings based on my recurring spendings",
    )
    assert stub_ai.last_request is not None
    answer = body["answer"]
    assert "163.00" in answer
    assert "not a monthly total or a forecast" in answer
    assert body["audit"]["spending_capture"] == "read_only_forecast"
    assert "Netflix subscription" in answer
    assert "Electric bill" in answer
    assert "Kopi" not in answer


def test_recurring_forecast_without_recurring_records(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("rf-u2", "Kopi", "food", 2.0, "2026-09-24")
    body = post_coach("rf-u2", "estimate my monthly recurring expenses")
    assert stub_ai.last_request is not None
    lowered = body["answer"].lower()
    assert "no recorded recurring" in lowered


def test_recurring_forecast_preserves_distinct_subscription_names(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("rf-u5", "Netflix", "entertainment", 48.0, "2026-09-01", True)
    add_transaction("rf-u5", "Netflix subscription", "entertainment", 15.0, "2026-07-20", True)
    body = post_coach("rf-u5", "estimate my monthly recurring expenses")
    assert stub_ai.last_request is not None
    assert "63.00" in body["answer"]
    assert "48.00" in body["answer"]
    assert body["answer"].count("Netflix") == 2


@pytest.mark.parametrize(
    "message",
    [
        "estimate my upcoming spendings based on my recurring spendings",
        "what are my recurring expenses?",
        "how much will I spend monthly with my recurring bills?",
    ],
)
def test_forecast_intent_detected(message: str, stub_ai: type[StubAIServiceClient]) -> None:
    body = post_coach("rf-u3", message)
    assert stub_ai.last_request is not None
    assert body["audit"]["spending_capture"] == "read_only_forecast"
    assert body["answer"] != "Stub guidance"


@pytest.mark.parametrize(
    "message",
    [
        "forecast my monthly spending",
        "project my upcoming expenses",
        "what is a recurring expense?",
        "explain recurring costs in a budget",
        "how much did I spend on 20/9?",
        "review my spending",
    ],
)
def test_forecast_not_triggered_for_education_or_other_queries(
    message: str, stub_ai: type[StubAIServiceClient]
) -> None:
    if "20/9" in message or "review" in message:
        post_coach("rf-u4", message)
        return
    body = post_coach("rf-u4", message)
    assert body["answer"] == "Stub guidance"
    assert stub_ai.last_request is not None
