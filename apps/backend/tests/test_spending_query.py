from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app
from app.services.spending_query import parse_date_spending_query

TODAY = date(2026, 9, 25)

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class StubAIServiceClient:
    last_request: CoachRequest | None = None
    draft: dict | None = None

    async def coach(self, request: CoachRequest) -> CoachResponse:
        StubAIServiceClient.last_request = request
        agent_results: list[dict] = []
        if StubAIServiceClient.draft is not None:
            agent_results = [
                {
                    "agent": "spending",
                    "summary": "Spending draft",
                    "rationale": ["Extracted a spending draft from the message."],
                    "confidence": 1.0,
                    "data": {"spending_draft": StubAIServiceClient.draft},
                }
            ]
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["spending"],
            answer="Stub guidance",
            agent_results=agent_results,
            disclaimers=["Educational guidance only."],
            audit={"source": "stub"},
        )


def query_draft(query_date: str | None = None) -> dict:
    return {
        "is_spending_request": True,
        "action": "query",
        "transactions": [],
        "query_date": query_date,
        "questions": [],
    }


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.transaction_capture as capture

    monkeypatch.setattr(capture, "_today", lambda: TODAY)


@pytest.fixture
def stub_ai() -> Iterator[type[StubAIServiceClient]]:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    StubAIServiceClient.last_request = None
    StubAIServiceClient.draft = None
    try:
        yield StubAIServiceClient
    finally:
        StubAIServiceClient.draft = None
        app.dependency_overrides.pop(get_ai_service_client, None)


def post_coach(user_id: str, message: str, session_id: str = "dq-s1") -> dict:
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": user_id, "session_id": session_id, "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_transaction(user_id: str, description: str, category: str, amount: float, on: str) -> None:
    response = client.post(
        f"/api/users/{user_id}/transactions",
        headers=HEADERS,
        json={
            "description": description,
            "category": category,
            "amount": {"currency": "SGD", "amount": amount},
            "occurred_on": on,
        },
    )
    assert response.status_code == 201, response.text


# --- parser ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("what is my spending on 21 Sep?", date(2026, 9, 21)),
        ("what is my spendings on 21 Sep?", date(2026, 9, 21)),
        ("how much did I spend on 21/9/2026?", date(2026, 9, 21)),
        ("what did I spend yesterday?", date(2026, 9, 24)),
        ("how much did I spend on Friday?", date(2026, 9, 18)),
        ("my spending on 15/9/2026", date(2026, 9, 15)),
        ("what did I spend on 21 Sep 2024?", date(2024, 9, 21)),
        ("can you let me know what have i spent on the 1st of Sep", date(2026, 9, 1)),
        ("what did I spend on Sep 1st?", date(2026, 9, 1)),
        ("what did I spend on 1st Sep?", date(2026, 9, 1)),
        ("how much did I spend on 22nd of September?", date(2026, 9, 22)),
        ("what did I spend on the 21st?", date(2026, 9, 21)),
    ],
)
def test_parse_date_spending_query_matches(message: str, expected: date) -> None:
    assert parse_date_spending_query(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "how much did I spend last month?",
        "review my spending",
        "what is my budget?",
        "how can I save more?",
        "what is my spending on tomorrow?",
        "did I buy anything on 21 Sep?",
    ],
)
def test_parse_date_spending_query_non_matches(message: str) -> None:
    assert parse_date_spending_query(message) is None


# --- route flow ----------------------------------------------------------------


def test_date_query_lists_only_matching_day_transactions(stub_ai: type[StubAIServiceClient]) -> None:
    add_transaction("dq-u1", "Chicken rice", "food", 5.0, "2026-09-21")
    add_transaction("dq-u1", "MRT top-up", "transport", 12.5, "2026-09-21")
    add_transaction("dq-u1", "Groceries", "food", 40.0, "2026-09-20")

    stub_ai.draft = query_draft("2026-09-21")
    body = post_coach("dq-u1", "what is my spending on 21/9/2026?")
    assert stub_ai.last_request is not None
    answer = body["answer"]
    assert "Chicken rice" in answer
    assert "MRT top-up" in answer
    assert "Groceries" not in answer
    assert "5.00" in answer
    assert "12.50" in answer
    assert "17.50" in answer


def test_date_query_no_transactions_on_day(stub_ai: type[StubAIServiceClient]) -> None:
    add_transaction("dq-u2", "Chicken rice", "food", 5.0, "2026-09-20")
    stub_ai.draft = query_draft("2026-09-21")
    body = post_coach("dq-u2", "what is my spending on 21/9/2026?")
    assert "no matching" in body["answer"].lower()


def test_date_query_without_any_data(stub_ai: type[StubAIServiceClient]) -> None:
    # The model leaves relative dates null; the backend resolves "yesterday".
    stub_ai.draft = query_draft(None)
    body = post_coach("dq-u3", "how much did I spend yesterday?")
    assert "no matching" in body["answer"].lower()


def test_non_date_spending_questions_still_go_to_ai(
    stub_ai: type[StubAIServiceClient],
) -> None:
    body = post_coach("dq-u4", "how much did I spend last month?")
    assert body["answer"] == "Stub guidance"
    assert stub_ai.last_request is not None
