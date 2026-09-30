from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app

TODAY = date(2026, 9, 25)

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class StubAIServiceClient:
    last_request: CoachRequest | None = None

    async def coach(self, request: CoachRequest) -> CoachResponse:
        StubAIServiceClient.last_request = request
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["spending"],
            answer="Stub guidance",
            agent_results=[],
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


def test_recurring_forecast_sums_latest_recurring_per_item(
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
    assert stub_ai.last_request is None
    answer = body["answer"]
    assert "148.00" in answer
    assert "Netflix subscription" in answer
    assert "Electric bill" in answer
    assert "Kopi" not in answer


def test_recurring_forecast_without_recurring_records(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("rf-u2", "Kopi", "food", 2.0, "2026-09-24")
    body = post_coach("rf-u2", "estimate my monthly recurring expenses")
    assert stub_ai.last_request is None
    lowered = body["answer"].lower()
    assert "no recurring" in lowered or "haven't recorded any recurring" in lowered


def test_recurring_forecast_dedupes_subscription_name_variants(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("rf-u5", "Netflix", "entertainment", 48.0, "2026-09-01", True)
    add_transaction("rf-u5", "Netflix subscription", "entertainment", 15.0, "2026-07-20", True)
    body = post_coach("rf-u5", "estimate my monthly recurring expenses")
    assert stub_ai.last_request is None
    assert "63.00" not in body["answer"]
    assert "48.00" in body["answer"]
    assert body["answer"].count("Netflix") == 1


@pytest.mark.parametrize(
    "message",
    [
        "estimate my upcoming spendings based on my recurring spendings",
        "what are my recurring expenses?",
        "forecast my monthly spending",
        "project my upcoming expenses",
        "how much will I spend monthly with my recurring bills?",
    ],
)
def test_forecast_intent_detected(message: str, stub_ai: type[StubAIServiceClient]) -> None:
    body = post_coach("rf-u3", message)
    assert stub_ai.last_request is None
    assert body["answer"] != "Stub guidance"


@pytest.mark.parametrize(
    "message",
    [
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
