from collections.abc import Iterator
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app
from app.services.transaction_capture import (
    PendingCaptureStore,
    classify_category,
    parse_date_expression,
    parse_spending_statement,
)

TODAY = date(2026, 9, 25)

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class StubAIServiceClient:
    last_request: CoachRequest | None = None

    async def coach(self, request: CoachRequest) -> CoachResponse:
        StubAIServiceClient.last_request = request
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["budget"],
            answer="Stub guidance",
            agent_results=[],
            disclaimers=["Educational guidance only."],
            audit={"source": "stub"},
        )


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.transaction_capture as capture

    monkeypatch.setattr(capture, "_today", lambda: TODAY)


@pytest.fixture(autouse=True)
def _clear_pending() -> Iterator[None]:
    from app.services.transaction_capture import pending_capture_store

    pending_capture_store.clear()
    yield
    pending_capture_store.clear()


@pytest.fixture
def stub_ai() -> Iterator[type[StubAIServiceClient]]:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    StubAIServiceClient.last_request = None
    try:
        yield StubAIServiceClient
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


def post_coach(user_id: str, message: str, session_id: str = "cap-s1") -> dict:
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": user_id, "session_id": session_id, "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


def transactions_for(user_id: str) -> list[dict]:
    response = client.get(f"/api/users/{user_id}/transactions", headers=HEADERS)
    assert response.status_code == 200
    return response.json()


def add_transaction(user_id: str, description: str, category: str, amount: float) -> None:
    response = client.post(
        f"/api/users/{user_id}/transactions",
        headers=HEADERS,
        json={
            "description": description,
            "category": category,
            "amount": {"currency": "SGD", "amount": amount},
            "occurred_on": "2026-09-20",
        },
    )
    assert response.status_code == 201, response.text


# --- parser positives -------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "amount", "description"),
    [
        ("i spent $5 on chicken rice", 5.0, "chicken rice"),
        ("$5 chicken rice", 5.0, "chicken rice"),
        ("paid 12.50 for MRT top-up", 12.5, "MRT top-up"),
        ("bought 3 packets of kopi", 3.0, "packets of kopi"),
        ("I spent SGD 42.90 on groceries", 42.9, "groceries"),
        ("I forked out 8 dollars for a taxi", 8.0, "taxi"),
        ("purchased a new mouse for 25.50", 25.5, "new mouse"),
        ("i have purchased a Coach bag today. I spent about 600 dollars", 600.0, "Coach bag"),
        ("i spent 12 dollars on mrt today", 12.0, "mrt"),
        ("i bought groceries yesterday for 38.50", 38.5, "groceries"),
        ("i took the mrt today. spent about 4.50", 4.5, "MRT"),
        ("took a grab home for 18 dollars", 18.0, "Grab"),
        ("i paid 18 dollars for a grab ride", 18.0, "Grab ride"),
        ("i bought a nintendo switch 2 costing about 750 dollars", 750.0, "nintendo switch 2"),
        ("got a iphone 15 pro, paid 1200 dollars", 1200.0, "iphone 15 pro"),
        ("I have spent 7.50 dollars on fried rice for today's lunch", 7.5, "Lunch (Fried Rice)"),
        ("i have booked for a $1288 anniversary dinner on the 28 sep", 1288.0, "anniversary dinner"),
    ],
)
def test_parse_spending_statement_positives(
    message: str, amount: float, description: str
) -> None:
    draft = parse_spending_statement(message)
    assert draft is not None
    assert draft.amount == amount
    assert draft.description.lower() == description.lower()


# --- parser negatives -------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "how much did I spend last month?",
        "review my spending",
        "I have $50 budget for food",
        "what is my highest spending category?",
        "hello there",
    ],
)
def test_parse_spending_statement_negatives(message: str) -> None:
    assert parse_spending_statement(message) is None


# --- date parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("today", TODAY),
        ("yesterday", TODAY - timedelta(days=1)),
        ("3 days ago", TODAY - timedelta(days=3)),
        ("Friday", date(2026, 9, 18)),
        ("21/9", date(2026, 9, 21)),
        ("21/9/2024", date(2024, 9, 21)),
        ("21 Sep", date(2026, 9, 21)),
        ("Sep 21", date(2026, 9, 21)),
        ("on 20 Sep", date(2026, 9, 20)),
        ("on the 20 Sep", date(2026, 9, 20)),
        ("it was yesterday", TODAY - timedelta(days=1)),
        ("the day before", TODAY - timedelta(days=2)),
        ("day before yesterday", TODAY - timedelta(days=2)),
    ],
)
def test_parse_date_expression(message: str, expected: date) -> None:
    assert parse_date_expression(message) == expected


def test_parse_date_expression_rejects_future_and_prose() -> None:
    assert parse_date_expression("25/12/2026") is None
    assert parse_date_expression("next friday") is None
    assert parse_date_expression("tell me about budgeting") is None


# --- category classification -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("chicken rice", "food"),
        ("lunch at mcdonalds", "food"),
        ("makan", "food"),
        ("MRT", "transport"),
        ("grab ride", "transport"),
        ("bus fare", "transport"),
        ("rent", "housing"),
        ("internet bill", "utilities"),
        ("paracetamol", "healthcare"),
        ("course fees", "education"),
        ("movie tickets", "entertainment"),
        ("new shoes", "shopping"),
        ("something random", "other"),
    ],
)
def test_classify_category(text: str, category: str) -> None:
    assert classify_category(text) == category


# --- pending store ------------------------------------------------------------


def test_pending_store_put_get_pop() -> None:
    store = PendingCaptureStore()
    assert store.get("u1") is None
    draft = parse_spending_statement("i spent $5 on chicken rice")
    assert draft is not None
    store.put("u1", draft)
    assert store.get("u1") is not None
    popped = store.pop("u1")
    assert popped is not None
    assert popped.amount == 5.0
    assert store.get("u1") is None


def test_pending_store_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PendingCaptureStore()
    draft = parse_spending_statement("i spent $5 on chicken rice")
    assert draft is not None
    fake_now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])
    store.put("u1", draft)
    assert store.get("u1") is not None
    fake_now[0] += 11 * 60
    assert store.get("u1") is None


# --- route flow ---------------------------------------------------------------


def test_coach_saves_statement_with_inline_date(stub_ai: type[StubAIServiceClient]) -> None:
    body = post_coach("cap-u1", "i spent $5 on chicken rice yesterday")
    assert stub_ai.last_request is None
    assert "chicken rice" in body["answer"].lower()
    assert "5" in body["answer"]
    saved = transactions_for("cap-u1")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 5.0
    assert saved[0]["category"] == "food"
    assert saved[0]["occurred_on"] == (TODAY - timedelta(days=1)).isoformat()


def test_coach_asks_for_date_then_saves_on_followup(
    stub_ai: type[StubAIServiceClient],
) -> None:
    first = post_coach("cap-u2", "i spent $5 on chicken rice")
    assert stub_ai.last_request is None
    assert "date" in first["answer"].lower() or "when" in first["answer"].lower()
    assert transactions_for("cap-u2") == []

    second = post_coach("cap-u2", "yesterday")
    assert stub_ai.last_request is None
    assert "saved" in second["answer"].lower() or "recorded" in second["answer"].lower()
    saved = transactions_for("cap-u2")
    assert len(saved) == 1
    assert saved[0]["category"] == "food"
    assert saved[0]["occurred_on"] == (TODAY - timedelta(days=1)).isoformat()


def test_coach_cancel_drops_pending(stub_ai: type[StubAIServiceClient]) -> None:
    post_coach("cap-u3", "i spent $5 on chicken rice")
    body = post_coach("cap-u3", "cancel")
    assert "nothing was saved" in body["answer"].lower()
    assert transactions_for("cap-u3") == []
    assert stub_ai.last_request is None


def test_coach_future_date_asks_again(stub_ai: type[StubAIServiceClient]) -> None:
    post_coach("cap-u4", "i spent $5 on chicken rice")
    body = post_coach("cap-u4", "25/12/2026")
    assert "future" in body["answer"].lower()
    assert transactions_for("cap-u4") == []

    followup = post_coach("cap-u4", "yesterday")
    assert "saved" in followup["answer"].lower() or "recorded" in followup["answer"].lower()
    assert len(transactions_for("cap-u4")) == 1


def test_coach_new_statement_replaces_pending(stub_ai: type[StubAIServiceClient]) -> None:
    post_coach("cap-u5", "i spent $5 on chicken rice")
    post_coach("cap-u5", "i paid $20 for petrol")
    body = post_coach("cap-u5", "yesterday")
    assert "petrol" in body["answer"].lower()
    saved = transactions_for("cap-u5")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 20.0


def test_coach_unrelated_message_while_pending_falls_through(
    stub_ai: type[StubAIServiceClient],
) -> None:
    post_coach("cap-u6", "i spent $5 on chicken rice")
    body = post_coach("cap-u6", "how can I save more each month?")
    assert body["answer"] == "Stub guidance"
    assert stub_ai.last_request is not None
    assert transactions_for("cap-u6") == []

    followup = post_coach("cap-u6", "yesterday")
    assert followup["answer"] == "Stub guidance"


def test_coach_unrelated_message_without_pending_unchanged(
    stub_ai: type[StubAIServiceClient],
) -> None:
    body = post_coach("cap-u7", "how much did I spend last month?")
    assert body["answer"] == "Stub guidance"
    assert stub_ai.last_request is not None
    assert transactions_for("cap-u7") == []


# --- budget flag on capture ------------------------------------------------------


def set_budget(user_id: str, categories: dict[str, float], period: str = "2026-09-01") -> None:
    response = client.put(
        f"/api/users/{user_id}/budget",
        headers=HEADERS,
        json={
            "period_start": period,
            "categories": [
                {"category": category, "limit_amount": limit}
                for category, limit in categories.items()
            ],
        },
    )
    assert response.status_code == 200, response.text


def test_capture_flags_category_budget_exceeded(stub_ai: type[StubAIServiceClient]) -> None:
    set_budget("cap-u8", {"food": 100.0})
    body = post_coach("cap-u8", "i spent $120 on chicken rice today")
    answer = body["answer"]
    assert "Saved" in answer
    assert "over" in answer.lower()
    assert "Food" in answer
    assert "120.00" in answer
    assert "100.00" in answer


def test_capture_no_budget_flag_within_limit(stub_ai: type[StubAIServiceClient]) -> None:
    set_budget("cap-u9", {"food": 100.0})
    body = post_coach("cap-u9", "i spent $20 on chicken rice today")
    lowered = body["answer"].lower()
    assert "saved" in lowered
    assert "over" not in lowered


def test_capture_no_budget_flag_without_budget(stub_ai: type[StubAIServiceClient]) -> None:
    body = post_coach("cap-u10", "i spent $500 on jewelry today")
    lowered = body["answer"].lower()
    assert "saved" in lowered
    assert "budget" not in lowered


def test_capture_saves_booking_with_future_date(stub_ai: type[StubAIServiceClient]) -> None:
    body = post_coach(
        "cap-u13", "i have booked for a $1288 anniversary dinner on the 28 Sep"
    )
    lowered = body["answer"].lower()
    assert "saved" in lowered
    assert "anniversary dinner" in lowered
    saved = transactions_for("cap-u13")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 1288.0
    assert saved[0]["occurred_on"] == "2026-09-28"
    assert saved[0]["category"] == "food"


def test_non_booking_still_rejects_future_date(stub_ai: type[StubAIServiceClient]) -> None:
    post_coach("cap-u14", "i spent $50 on dinner")
    body = post_coach("cap-u14", "28/9/2026")
    assert "future" in body["answer"].lower()
    assert transactions_for("cap-u14") == []


def test_capture_saves_title_cased_description(stub_ai: type[StubAIServiceClient]) -> None:
    post_coach("cap-u15", "i spent $5 on chicken rice today")
    saved = transactions_for("cap-u15")
    assert saved[0]["description"] == "Chicken Rice"


# --- batch capture ---------------------------------------------------------------

BATCH_MESSAGE = (
    "Help me add my following expenses:\n"
    "\n"
    "Spent $3.50 for lunch (Fried Rice) on 05 Sep\n"
    "Booked an anniversary dinner that costs 888 dollars on 15 Sep"
)


def test_batch_saves_multiple_dated_lines(stub_ai: type[StubAIServiceClient]) -> None:
    body = post_coach("cap-b1", BATCH_MESSAGE)
    assert stub_ai.last_request is None
    answer = body["answer"]
    assert "no transactions" not in answer.lower()
    assert "3.50" in answer
    assert "888.00" in answer
    saved = transactions_for("cap-b1")
    assert len(saved) == 2
    assert sorted(item["occurred_on"] for item in saved) == ["2026-09-05", "2026-09-15"]
    assert {item["category"] for item in saved} == {"food"}


def test_batch_with_undated_line_asks_then_saves(
    stub_ai: type[StubAIServiceClient],
) -> None:
    first = post_coach(
        "cap-b2",
        "add these expenses:\nSpent $5 on coffee\nSpent $12 on mrt yesterday",
    )
    assert stub_ai.last_request is None
    assert "when" in first["answer"].lower()
    saved = transactions_for("cap-b2")
    assert len(saved) == 1
    assert saved[0]["category"] == "transport"

    second = post_coach("cap-b2", "yesterday")
    assert "coffee" in second["answer"].lower()
    saved = transactions_for("cap-b2")
    assert len(saved) == 2
    coffee = next(item for item in saved if item["category"] == "food")
    assert coffee["occurred_on"] == (TODAY - timedelta(days=1)).isoformat()


def test_batch_cancel_drops_all_undated(stub_ai: type[StubAIServiceClient]) -> None:
    post_coach("cap-b3", "log expenses:\nSpent $5 on coffee\nSpent $12 on movie tickets")
    assert transactions_for("cap-b3") == []
    body = post_coach("cap-b3", "cancel")
    assert "nothing was saved" in body["answer"].lower()
    assert transactions_for("cap-b3") == []


def test_batch_multi_pending_asks_next_after_date(
    stub_ai: type[StubAIServiceClient],
) -> None:
    first = post_coach(
        "cap-b4",
        "log expenses:\nSpent $5 on coffee\nSpent $12 on movie tickets",
    )
    assert "when" in first["answer"].lower()
    second = post_coach("cap-b4", "yesterday")
    assert "movie" in second["answer"].lower() or "tickets" in second["answer"].lower()
    assert "when" in second["answer"].lower()
    assert len(transactions_for("cap-b4")) == 1
    post_coach("cap-b4", "the day before")
    assert len(transactions_for("cap-b4")) == 2


def test_two_sentences_saved_as_batch(stub_ai: type[StubAIServiceClient]) -> None:
    post_coach(
        "cap-b5", "I spent $5 on coffee today. I paid $10 for lunch yesterday"
    )
    assert stub_ai.last_request is None
    saved = transactions_for("cap-b5")
    assert len(saved) == 2


# --- transaction.added telemetry log --------------------------------------------


def _added_events(caplog: pytest.LogCaptureFixture) -> list[dict]:
    import json

    events = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if payload.get("event") == "transaction.added":
            events.append(payload)
    return events


def test_transaction_added_log_emitted_via_api(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="service.calls")
    add_transaction("cap-u11", "MRT top-up", "transport", 12.5)
    events = _added_events(caplog)
    assert len(events) == 1
    assert events[0]["source"] == "api"
    assert events[0]["category"] == "transport"
    assert "amount" not in events[0]


def test_transaction_added_log_emitted_via_capture(
    caplog: pytest.LogCaptureFixture, stub_ai: type[StubAIServiceClient]
) -> None:
    caplog.set_level("INFO", logger="service.calls")
    post_coach("cap-u12", "i spent $5 on chicken rice today")
    events = _added_events(caplog)
    assert len(events) == 1
    assert events[0]["source"] == "coach_capture"
    assert events[0]["category"] == "food"
    assert "amount" not in events[0]
