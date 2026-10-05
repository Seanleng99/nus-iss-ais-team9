from collections.abc import Iterator
from datetime import date, timedelta
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from language_fixtures import language_case

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app
from app.services.transaction_capture import (
    PendingCaptureStore,
    classify_category,
    parse_batch,
    parse_date_expression,
    parse_spending_details,
    parse_spending_statement,
)

TODAY = date(2026, 9, 25)

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}


class StubAIServiceClient:
    last_request: CoachRequest | None = None
    draft: dict | None = None
    drafts: ClassVar[list[dict]] = []

    async def coach(self, request: CoachRequest) -> CoachResponse:
        StubAIServiceClient.last_request = request
        draft = StubAIServiceClient.drafts.pop(0) if StubAIServiceClient.drafts else StubAIServiceClient.draft
        agent_results: list[dict] = []
        if draft is not None:
            agent_results = [
                {
                    "agent": "spending",
                    "summary": "Spending draft",
                    "rationale": ["Extracted a spending draft from the message."],
                    "confidence": 1.0,
                    "data": {"spending_draft": draft},
                }
            ]
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["spending"],
            answer="Stub guidance",
            agent_results=agent_results,
            disclaimers=["Educational guidance only."],
            audit={"source": "stub", "turn_decision": {
                "budget_status_query": request.message == "is my spending okay this month?",
            }},
        )


def txn(
    description: str | None,
    amount: float | None = None,
    occurred_on: str | None = None,
    *,
    recurring: bool = False,
    booking: bool = False,
) -> dict:
    return {
        "description": description,
        "amount": amount,
        "category": None,
        "occurred_on": occurred_on,
        "recurring": recurring,
        "booking": booking,
    }


def record(*items: dict, questions: list[str] | None = None) -> dict:
    return {
        "is_spending_request": True,
        "action": "record",
        "transactions": list(items),
        "query_date": None,
        "questions": questions or [],
    }


def empty_record() -> dict:
    return record()


def query(query_date: str | None = None) -> dict:
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


@pytest.fixture(autouse=True)
def _clear_pending() -> Iterator[None]:
    from app.services.transaction_capture import (
        pending_capture_store,
    )

    pending_capture_store.clear()
    yield
    pending_capture_store.clear()


@pytest.fixture
def stub_ai() -> Iterator[type[StubAIServiceClient]]:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    StubAIServiceClient.last_request = None
    StubAIServiceClient.draft = None
    StubAIServiceClient.drafts = []
    try:
        yield StubAIServiceClient
    finally:
        StubAIServiceClient.draft = None
        StubAIServiceClient.drafts = []
        app.dependency_overrides.pop(get_ai_service_client, None)


def post_coach(user_id: str, message: str, session_id: str = "cap-s1", *, budget_period_start: str | None = None) -> dict:
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": user_id, "session_id": session_id, "message": message,
              **({"budget_period_start": budget_period_start} if budget_period_start else {})},
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
        (
            "i have booked for a $1288 anniversary dinner on the 28 sep",
            1288.0,
            "anniversary dinner",
        ),
        # item-first ledger style (no verb)
        ("lunch 5.50", 5.5, "lunch"),
        ("toll 3.50", 3.5, "toll"),
        ("haircut 25", 25.0, "haircut"),
        ("uber ride 22", 22.0, "uber ride"),
        ("school fees 800", 800.0, "school fees"),
        ("lta road tax 1100", 1100.0, "lta road tax"),
        ("property tax 3400", 3400.0, "property tax"),
        ("4.30 kopi", 4.3, "kopi"),
        ("grand 18 grab", 18.0, "grab"),
        ("uniform 120", 120.0, "uniform"),
        ("PTPTN repayment 200", 200.0, "ptptn repayment"),
        ("gcash 500 load", 500.0, "gcash load"),
        ("topup mrt 20", 20.0, "topup mrt"),
        ("CPF top-up 300", 300.0, "cpf top-up"),
        ("got haircut yesterday 25", 25.0, "haircut"),
        (
            "can you help me add my Spotify monthly subscription that costs 10.90",
            10.9,
            "Spotify monthly subscription",
        ),
        (
            "can you help me add a transaction Spotify monthly subscription that costs 10.90",
            10.9,
            "Spotify monthly subscription",
        ),
        ("please log a 4.50 bus fare", 4.5, "bus fare"),
        ("cny groceries at NTUC 88.40", 88.4, "cny groceries ntuc"),
        ("vax travel insurance 42", 42.0, "vax travel insurance"),
        ("split the bill, my part 13.50", 13.5, "split bill part"),
        # noun phrase + marked amount, no verb
        ("dinner at jumbo seafood $120", 120.0, "dinner jumbo seafood"),
        ("breakfast at old kopitiam 7.20", 7.2, "breakfast old kopitiam"),
        ("shopee haul 67.80", 67.8, "shopee haul"),
        ("insurance premium 1,200", 1200.0, "insurance premium"),
        ("mrt monthly pass 128", 128.0, "mrt monthly pass"),
        ("car wash 12", 12.0, "car wash"),
        # copula phrasing
        ("grab was 18", 18.0, "grab"),
        ("the mall parking was 4.50", 4.5, "mall parking"),
        ("my rent is 2800", 2800.0, "rent"),
        ("flight to tokyo cost me 2000", 2000.0, "flight tokyo"),
        ("cost me 30 for the tow", 30.0, "tow"),
        ("charged 450 for car service", 450.0, "car service"),
        # extended verbs
        ("spend 20 for parking", 20.0, "parking"),
        ("settled the credit card bill 1500", 1500.0, "credit card bill"),
        ("gave ah beng 50 for the renovation", 50.0, "ah beng renovation"),
        ("sent mum 300 last night", 300.0, "mum"),
        ("mailed 300 sgd to mum", 300.0, "mum"),
        ("donated 100 to the temple", 100.0, "temple"),
        ("treat customers lunch 200", 200.0, "customers lunch"),
        ("angbao gave out 300", 300.0, "angbao"),
        ("i grabbed food 12", 12.0, "food"),
        ("transacted 12 at 7-eleven", 12.0, "7-eleven"),
        # money formats
        ("coffee -4.30", 4.3, "coffee"),
        ("spent 30k for the wedding", 30000.0, "wedding"),
        ("movie tix 13.50 x 2", 27.0, "movie tix"),
        # light Chinese support
        (
            language_case("transaction_capture.test_parse_spending_statement_positives"),
            5.0,
            language_case("transaction_capture.test_parse_spending_statement_positives_2"),
        ),
        (
            language_case("transaction_capture.test_parse_spending_statement_positives_3"),
            3.5,
            language_case("transaction_capture.test_parse_spending_statement_positives_4"),
        ),
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
        "the weather is nice today 30 degrees",
        "i owe ah lat 40 for the tickets",
        "my monthly income is 6000",
        "i am 35 years old",
        "how many days until 25/12",
        "private question 43210",
        "error code 500",
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


def test_ordinal_day_before_month_uses_month_not_current_month() -> None:
    from app.services.transaction_capture import extract_date_from_text

    msg = "can you tell me what transactions do i have on the 3rd Oct"
    assert extract_date_from_text(msg, allow_future=True) == date(2026, 10, 3)
    assert extract_date_from_text("the 3rd Oct", allow_future=True) == date(2026, 10, 3)
    assert extract_date_from_text("what did I spend on the 21st?", allow_future=True) == date(
        2026, 9, 21
    )


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
        ("utilities", "utilities"),
        ("utilites", "utilities"),
        ("utility bill", "utilities"),
        ("paracetamol", "healthcare"),
        ("course fees", "education"),
        ("movie tickets", "entertainment"),
        ("new shoes", "shopping"),
        ("something random", "other"),
    ],
)
def test_classify_category(text: str, category: str) -> None:
    assert classify_category(text) == category


# --- amount slot filling ---------------------------------------------------------


def test_parse_spending_details_extracts_description_and_date_without_amount() -> None:
    draft = parse_spending_details("A flight ticket to Sydney today-got it.")
    assert draft is not None
    assert draft.amount == 0.0
    assert "flight" in draft.description.lower()
    assert draft.category == "transport"
    assert draft.when == TODAY


def test_parse_spending_details_rejects_questions_and_prose() -> None:
    assert parse_spending_details("How much was the flight ticket?") is None
    assert parse_spending_details("hello there") is None
    assert parse_spending_details("i spent $5 on chicken rice") is None


def test_coach_asks_for_amount_then_saves_on_followup(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [
        record(txn("Flight ticket to Sydney")),
        record(txn("Flight ticket to Sydney", 850.0, TODAY.isoformat())),
    ]
    first = post_coach(
        "cap-a1", "A flight ticket to Sydney today-got it. What was the ticket price?"
    )
    assert "how much" in first["answer"].lower()
    assert transactions_for("cap-a1") == []

    second = post_coach("cap-a1", "it was about 850")
    assert stub_ai.last_request is not None
    assert "saved" in second["answer"].lower()
    saved = transactions_for("cap-a1")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 850.0
    assert "flight" in saved[0]["description"].lower()
    assert saved[0]["occurred_on"] == TODAY.isoformat()


def test_coach_amount_followup_accepts_marked_amount(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [
        record(txn("New Phone")),
        record(txn("New Phone", 1288.0, (TODAY - timedelta(days=1)).isoformat())),
    ]
    post_coach("cap-a2", "Bought a new phone yesterday")
    second = post_coach("cap-a2", "$1288")
    assert "saved" in second["answer"].lower()
    saved = transactions_for("cap-a2")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 1288.0
    assert saved[0]["occurred_on"] == (TODAY - timedelta(days=1)).isoformat()


def test_coach_amount_followup_cancel(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.drafts = [record(txn("New Phone")), None]
    post_coach("cap-a3", "Bought a new phone yesterday")
    body = post_coach("cap-a3", "cancel")
    assert "nothing was saved" in body["answer"].lower()
    assert transactions_for("cap-a3") == []


def test_coach_complete_statement_saves_immediately(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    body = post_coach("cap-a4", "i spent $5 on chicken rice today")
    assert stub_ai.last_request is not None
    assert "saved" in body["answer"].lower()
    assert "how much" not in body["answer"].lower()
    assert len(transactions_for("cap-a4")) == 1


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
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    body = post_coach("cap-u1", "i spent $5 on chicken rice yesterday")
    assert stub_ai.last_request is not None
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
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    first = post_coach("cap-u2", "i spent $5 on chicken rice")
    assert "date" in first["answer"].lower() or "when" in first["answer"].lower()
    assert transactions_for("cap-u2") == []

    second = post_coach("cap-u2", "yesterday")
    assert "saved" in second["answer"].lower() or "recorded" in second["answer"].lower()
    saved = transactions_for("cap-u2")
    assert len(saved) == 1
    assert saved[0]["category"] == "food"
    assert saved[0]["occurred_on"] == (TODAY - timedelta(days=1)).isoformat()


def test_coach_cancel_drops_pending(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.drafts = [record(txn("Chicken Rice", 5.0)), None, None]
    post_coach("cap-u3", "i spent $5 on chicken rice")
    body = post_coach("cap-u3", "cancel")
    assert "nothing was saved" in body["answer"].lower()
    assert transactions_for("cap-u3") == []

    # The dropped draft must not come back to life on a later bare date.
    post_coach("cap-u3", "yesterday")
    assert transactions_for("cap-u3") == []


def test_coach_future_date_asks_again(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    post_coach("cap-u4", "i spent $5 on chicken rice")
    body = post_coach("cap-u4", "25/12/2026")
    assert "future" in body["answer"].lower()
    assert transactions_for("cap-u4") == []

    followup = post_coach("cap-u4", "yesterday")
    assert "saved" in followup["answer"].lower() or "recorded" in followup["answer"].lower()
    assert len(transactions_for("cap-u4")) == 1


def test_coach_new_statement_replaces_pending(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    post_coach("cap-u5", "i spent $5 on chicken rice")
    stub_ai.draft = record(txn("Petrol", 20.0))
    post_coach("cap-u5", "i paid $20 for petrol")
    body = post_coach("cap-u5", "yesterday")
    assert "petrol" in body["answer"].lower()
    saved = transactions_for("cap-u5")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 20.0


def test_coach_unrelated_message_while_pending_falls_through(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [record(txn("Chicken Rice", 5.0)), None, None]
    post_coach("cap-u6", "i spent $5 on chicken rice")
    body = post_coach("cap-u6", "how can I save more each month?")
    assert body["answer"] == "Stub guidance"
    assert stub_ai.last_request is not None
    assert transactions_for("cap-u6") == []

    # The abandoned draft must not resurrect via a later bare date.
    followup = post_coach("cap-u6", "yesterday")
    assert followup["answer"] == "Stub guidance"
    assert transactions_for("cap-u6") == []


def test_coach_unrelated_message_without_pending_unchanged(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = None
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
    stub_ai.draft = record(txn("Chicken Rice", 120.0))
    body = post_coach("cap-u8", "i spent $120 on chicken rice today")
    answer = body["answer"]
    assert "Saved" in answer
    assert "over" in answer.lower()
    assert "Food" in answer
    assert "120.00" in answer
    assert "100.00" in answer


def test_capture_no_budget_flag_within_limit(stub_ai: type[StubAIServiceClient]) -> None:
    set_budget("cap-u9", {"food": 100.0})
    stub_ai.draft = record(txn("Chicken Rice", 20.0))
    body = post_coach("cap-u9", "i spent $20 on chicken rice today")
    lowered = body["answer"].lower()
    assert "saved" in lowered
    assert "over" not in lowered


def test_capture_no_budget_flag_without_budget(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Jewelry", 500.0))
    body = post_coach("cap-u10", "i spent $500 on jewelry today")
    lowered = body["answer"].lower()
    assert "saved" in lowered
    assert "budget" not in lowered


def test_capture_saves_booking_with_future_date(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Anniversary Dinner", 1288.0, "2026-09-28", booking=True))
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
    stub_ai.draft = record(txn("Dinner", 50.0))
    post_coach("cap-u14", "i spent $50 on dinner")
    body = post_coach("cap-u14", "28/9/2026")
    assert "future" in body["answer"].lower()
    assert transactions_for("cap-u14") == []


def test_capture_saves_title_cased_description(stub_ai: type[StubAIServiceClient]) -> None:
    # The draft's description is stored as given; the AI is instructed to title-case.
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    post_coach("cap-u15", "i spent $5 on chicken rice today")
    saved = transactions_for("cap-u15")
    assert saved[0]["description"] == "Chicken Rice"


def test_polite_add_request_saves_recurring_subscription(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = record(txn("Spotify Monthly Subscription", 10.9, recurring=True))
    body = post_coach(
        "cap-r1", "can you help me add my Spotify monthly subscription that costs 10.90 today"
    )
    assert "saved" in body["answer"].lower()
    saved = transactions_for("cap-r1")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 10.9
    assert saved[0]["recurring"] is True


# --- amend the last saved transaction -----------------------------------------


def test_amend_updates_last_saved_amount(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.drafts = [record(txn("Youtube Subscription", 19.9))]
    post_coach("cap-m1", "i spent 19.90 on youtube subscription today")
    body = post_coach("cap-m1", "oh sorry its 18.90")
    assert "updated" in body["answer"].lower()
    assert "18.90" in body["answer"]
    saved = transactions_for("cap-m1")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 18.9
    assert saved[0]["description"] == "Youtube Subscription"


def test_amend_with_cost_verb_and_instead(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Lunch McDonalds", 8.5))
    post_coach("cap-m8", "i have ate mcdonalds for lunch today it costs 8.50")
    body = post_coach("cap-m8", "sorry, it costs 9.50 instead")
    assert "updated" in body["answer"].lower()
    assert "9.50" in body["answer"]
    saved = transactions_for("cap-m8")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 9.5


def test_amend_with_that_was_rather(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Grab", 30.0))
    post_coach("cap-m9", "i spent 30 on grab today")
    body = post_coach("cap-m9", "oops that was 42 dollars rather")
    assert "updated" in body["answer"].lower()
    saved = transactions_for("cap-m9")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 42.0


def test_amend_updates_last_saved_date(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Dinner", 20.0))
    post_coach("cap-m2", "i spent $20 on dinner today")
    body = post_coach("cap-m2", "oh sorry it was yesterday")
    assert "updated" in body["answer"].lower()
    saved = transactions_for("cap-m2")
    assert len(saved) == 1
    assert saved[0]["occurred_on"] == "2026-09-24"
    assert saved[0]["amount"]["amount"] == 20.0


def test_amend_updates_amount_and_date(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Movie Tickets", 20.0))
    post_coach("cap-m3", "i spent $20 on movie tickets today")
    body = post_coach("cap-m3", "actually make it 35 dollars yesterday")
    assert "updated" in body["answer"].lower()
    saved = transactions_for("cap-m3")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 35.0
    assert saved[0]["occurred_on"] == "2026-09-24"


def test_amend_without_last_saved_transaction_falls_through(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = None
    body = post_coach("cap-m4", "oh sorry its 18.90")
    assert body["answer"] == "Stub guidance"
    assert transactions_for("cap-m4") == []


def test_statement_after_prefix_word_still_captures(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [record(txn("Kopi", 5.0)), record(txn("Lunch", 20.0))]
    post_coach("cap-m5", "i spent 5 on kopi today")
    post_coach("cap-m5", "actually i spent $20 for lunch today")
    saved = transactions_for("cap-m5")
    assert len(saved) == 2
    assert sorted(item["amount"]["amount"] for item in saved) == [5.0, 20.0]


def test_amend_recomputes_budget_flag(stub_ai: type[StubAIServiceClient]) -> None:
    set_budget("cap-m6", {"food": 100.0})
    stub_ai.draft = record(txn("Chicken Rice", 90.0))
    post_coach("cap-m6", "i spent $90 on chicken rice today")
    body = post_coach("cap-m6", "oh sorry its 120")
    lowered = body["answer"].lower()
    assert "updated" in lowered
    assert "over" in lowered
    assert "120.00" in body["answer"]


def test_amend_applies_again_to_same_transaction(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = record(txn("Internet Bill", 19.9))
    post_coach("cap-m7", "i spent 19.90 on internet bill today")
    post_coach("cap-m7", "oh sorry its 18.90")
    body = post_coach("cap-m7", "oh sorry make it 17.50")
    assert "updated" in body["answer"].lower()
    saved = transactions_for("cap-m7")
    assert len(saved) == 1
    assert saved[0]["amount"]["amount"] == 17.5


# --- batch capture ---------------------------------------------------------------

BATCH_MESSAGE = (
    "Help me add my following expenses:\n"
    "\n"
    "Spent $3.50 for lunch (Fried Rice) on 05 Sep\n"
    "Booked an anniversary dinner that costs 888 dollars on 15 Sep"
)


def test_batch_saves_multiple_dated_lines(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(
        txn("Lunch (Fried Rice)", 3.5, "2026-09-05"),
        txn("Anniversary Dinner", 888.0, "2026-09-15", booking=True),
    )
    body = post_coach("cap-b1", BATCH_MESSAGE)
    assert stub_ai.last_request is not None
    answer = body["answer"]
    assert "no transactions" not in answer.lower()
    assert "3.50" in answer
    assert "888.00" in answer
    saved = transactions_for("cap-b1")
    assert len(saved) == 2
    assert sorted(item["occurred_on"] for item in saved) == ["2026-09-05", "2026-09-15"]
    assert {item["category"] for item in saved} == {"food"}


def test_batch_with_undated_line_saves_dated_then_asks(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [
        record(txn("Coffee", 5.0), txn("MRT", 12.0)),
        record(txn("Coffee", 5.0)),
    ]
    first = post_coach(
        "cap-b2",
        "add these expenses:\nSpent $5 on coffee\nSpent $12 on mrt yesterday",
    )
    assert "when" in first["answer"].lower()
    assert "saved" in first["answer"].lower()
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
    stub_ai.draft = record(txn("Coffee", 5.0), txn("Movie Tickets", 12.0))
    post_coach("cap-b3", "log expenses:\nSpent $5 on coffee\nSpent $12 on movie tickets")
    assert transactions_for("cap-b3") == []
    body = post_coach("cap-b3", "cancel")
    assert "nothing was saved" in body["answer"].lower()
    assert transactions_for("cap-b3") == []


def test_batch_one_date_completes_all_dateless_lines(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = record(txn("Coffee", 5.0), txn("Movie Tickets", 12.0))
    first = post_coach(
        "cap-b4",
        "log expenses:\nSpent $5 on coffee\nSpent $12 on movie tickets",
    )
    assert "when" in first["answer"].lower()
    assert len(transactions_for("cap-b4")) == 0
    second = post_coach("cap-b4", "yesterday")
    assert "saved" in second["answer"].lower()
    assert "when" not in second["answer"].lower()
    assert len(transactions_for("cap-b4")) == 2


def test_two_sentences_saved_as_batch(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Coffee", 5.0), txn("Lunch", 10.0))
    post_coach(
        "cap-b5", "I spent $5 on coffee today. I paid $10 for lunch yesterday"
    )
    assert stub_ai.last_request is not None
    saved = transactions_for("cap-b5")
    assert len(saved) == 2


def test_comma_and_and_list_splits_into_three_drafts() -> None:
    drafts = parse_batch("today i spent 30 on grab, 10 on lunch, and 15 on dinner")
    assert drafts is not None
    assert len(drafts) == 3
    assert sorted(draft.amount for draft in drafts) == [10.0, 15.0, 30.0]
    assert all(draft.when == TODAY for draft in drafts)
    assert sorted(draft.description.lower() for draft in drafts) == [
        "dinner",
        "grab",
        "lunch",
    ]


def test_comma_list_saves_three_transactions(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(
        txn("Grab", 30.0),
        txn("Lunch", 10.0),
        txn("Dinner", 15.0),
    )
    body = post_coach("cap-c1", "today i spent 30 on grab, 10 on lunch, and 15 on dinner")
    assert "when" not in body["answer"].lower()
    saved = transactions_for("cap-c1")
    assert len(saved) == 3
    assert sorted(item["amount"]["amount"] for item in saved) == [10.0, 15.0, 30.0]
    assert {item["occurred_on"] for item in saved} == {TODAY.isoformat()}


def test_multiline_header_date_applies_to_all_items() -> None:
    drafts = parse_batch("yesterday i spent\n150 on utilites\n20 on a small fan")
    assert drafts is not None
    assert len(drafts) == 2
    assert all(draft.when == TODAY - timedelta(days=1) for draft in drafts)


def test_multiline_header_date_saves_all_without_followup(
    stub_ai: type[StubAIServiceClient],
) -> None:
    # The draft leaves occurred_on null; the backend resolves the header's
    # "yesterday" for every line, so everything saves in one turn.
    stub_ai.draft = record(txn("Utilites", 150.0), txn("Small Fan", 20.0))
    body = post_coach("cap-md1", "yesterday i spent\n150 on utilites\n20 on a small fan")
    assert stub_ai.last_request is not None
    assert "when" not in body["answer"].lower()
    saved = transactions_for("cap-md1")
    assert len(saved) == 2
    assert {item["occurred_on"] for item in saved} == {(TODAY - timedelta(days=1)).isoformat()}
    utilites = [item for item in saved if item["description"] == "Utilites"]
    assert [item["category"] for item in utilites] == ["utilities"]


def test_comma_split_needs_amounts_in_every_part() -> None:
    assert parse_batch("split the bill, my part 13.50") is None
    assert parse_batch("i bought groceries and snacks for 38.50") is None


def test_multi_item_and_splits_into_two_drafts() -> None:
    drafts = parse_batch("bought a phone 1288 and a case 45")
    assert drafts is not None
    assert [draft.amount for draft in drafts] == [1288.0, 45.0]


def test_multi_item_and_saves_two_transactions(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Phone", 1288.0, "2026-09-20"), txn("Case", 45.0, "2026-09-21"))
    body = post_coach("cap-m1", "bought a phone 1288 on 20 Sep and a case 45 on 21 Sep")
    assert "1288.00" in body["answer"]
    assert "45.00" in body["answer"]
    saved = transactions_for("cap-m1")
    assert len(saved) == 2


# --- transaction listing queries ---------------------------------------------------


def test_listing_query_resolved_locally(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.drafts = [record(txn("Groceries", 12.0)), query(TODAY.isoformat())]
    body = post_coach("q-t2", "i spent $12 on groceries today")
    assert "saved" in body["answer"].lower()
    listed = post_coach("q-t2", "show me my today's transactions")
    answer = listed["answer"].lower()
    assert "groceries" in answer
    assert "12.00" in listed["answer"]


def test_listing_query_variants_parse() -> None:
    from datetime import date as _date

    from app.services.spending_query import parse_date_spending_query

    assert parse_date_spending_query("show me my today's transactions") == TODAY
    assert (
        parse_date_spending_query("what transactions did i make yesterday")
        == TODAY - timedelta(days=1)
    )
    assert parse_date_spending_query("list my purchases from 21/9") == _date(2026, 9, 21)
    assert parse_date_spending_query("show me my transactions") is None
    assert parse_date_spending_query("show me my budget today") is None
    assert parse_date_spending_query(
        "can you tell me what transactions do i have on the 3rd Oct"
    ) == _date(2026, 10, 3)
    assert parse_date_spending_query("what transactions do i have on 3/10") == _date(
        2026, 10, 3
    )


def test_listing_query_lists_booked_future_transactions(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [
        record(txn("Flight To Tokyo", 150.0, "2026-10-03", booking=True)),
        query("2026-10-03"),
    ]
    body = post_coach("q-t3", "i have booked a flight to tokyo for $150 on the 3rd Oct")
    assert "saved" in body["answer"].lower()
    listed = post_coach("q-t3", "what transactions do i have on the 3rd Oct")
    assert "flight" in listed["answer"].lower()
    assert "150.00" in listed["answer"]


# --- named transaction edit with confirmation --------------------------------------


@pytest.mark.parametrize("message,expected", [
    ("confirm transaction", "saved"), ("cancel transaction", "cancelled"),
    (language_case("transaction_preview.confirm.zh"), "saved"),
    (language_case("transaction_preview.cancel.zh"), "cancelled"),
])
def test_coach_explicit_preview_waits_for_confirmation(stub_ai: type[StubAIServiceClient], message, expected):
    stub_ai.draft = {**record(txn("Chicken rice", 5, "2026-09-24")), "persistence_intent": "preview"}
    preview = post_coach("cap-preview", "I spent $5 on chicken rice yesterday. Prepare it for review.")
    assert preview["audit"]["action_status"] == "preview"
    assert preview["audit"]["spending_capture"] == "awaiting_confirmation"
    assert "Chicken rice" in preview["answer"] and "5.00" in preview["answer"]
    assert transactions_for("cap-preview") == []
    outcome = post_coach("cap-preview", message)
    assert outcome["audit"]["action_status"] == expected
    assert len(transactions_for("cap-preview")) == (1 if expected == "saved" else 0)


def test_explicit_read_only_aggregate_uses_authenticated_selected_month(stub_ai):
    for owner, category, amount, day in [
        ("cap-selected-total", "dining", 20, "2026-09-01"),
        ("cap-selected-total", "dining", 30, "2026-09-02"),
        ("cap-selected-total", "transport", 999, "2026-09-02"),
        ("cap-selected-total", "dining", 555, "2026-10-01"),
        ("another-owner", "dining", 777, "2026-09-02"),
    ]:
        saved = client.post(f"/api/users/{owner}/transactions", headers=HEADERS, json={
            "description": "Recorded expense", "category": category,
            "amount": {"amount": amount}, "occurred_on": day,
        })
        assert saved.status_code == 201
    stub_ai.draft = {**query(), "query_scope": "selected_period", "query_categories": ["dining"]}
    result = post_coach("cap-selected-total", "What is the total recorded dining spend? Answer in one short sentence.",
                        budget_period_start="2026-09-01")
    assert result["audit"]["action_status"] == "read_only_query"
    assert "50.00" in result["answer"] and "2026-09-01" in result["answer"]
    assert "555.00" not in result["answer"] and "999.00" not in result["answer"] and "777.00" not in result["answer"]
    assert stub_ai.last_request.snapshot.period_start == "2026-09-01"


@pytest.mark.parametrize("operation", ["lookup", "record"])
def test_selected_month_never_fills_a_missing_lookup_or_expense_date(stub_ai, operation):
    stub_ai.draft = query() if operation == "lookup" else record(txn("Chicken rice", 5))
    message = "Show my transactions." if operation == "lookup" else "I spent $5 on chicken rice."
    result = post_coach("cap-selected-missing-date", message, budget_period_start="2026-09-01")
    assert result["audit"]["action_status"] == "needs_input"
    assert transactions_for("cap-selected-missing-date") == []
    assert "which day" in result["answer"].lower() if operation == "lookup" else "when" in result["answer"].lower()


def test_confirmed_recurring_expense_reports_persisted_schedule_and_cannot_resave(stub_ai):
    terms = {"frequency": "monthly", "interval": 1, "first_on": "2026-01-31",
             "next_due_on": "2026-02-28", "last_on": "2026-12-31"}
    stub_ai.draft = record({**txn("Rent", 100, "2026-01-31"), "recurrence": terms})
    preview = post_coach("cap-recurring-confirmed-terms", "Prepare my monthly rent expense for review.")
    assert preview["audit"]["action_status"] == "preview"
    assert transactions_for("cap-recurring-confirmed-terms") == []
    stub_ai.draft = None
    confirmed = post_coach("cap-recurring-confirmed-terms", "confirm transaction")
    assert confirmed["audit"]["action_status"] == "saved"
    assert all(day in confirmed["answer"] for day in ["2026-01-31", "2026-02-28", "2026-12-31"])
    assert "month(s)" in confirmed["answer"] and "every 1" in confirmed["answer"]
    rows = transactions_for("cap-recurring-confirmed-terms")
    assert len(rows) == 1 and rows[0]["recurrence"] == {**terms, "month_end": False}
    assert rows[0]["obligation_id"] not in confirmed["answer"]
    assert confirmed["audit"]["confirmed_recurrences"] == [{
        "description": "Rent", "amount": {"currency": "SGD", "amount": 100.0},
        "recurrence": rows[0]["recurrence"],
    }]
    post_coach("cap-recurring-confirmed-terms", "confirm transaction")
    assert len(transactions_for("cap-recurring-confirmed-terms")) == 1


@pytest.mark.parametrize("reply", ["yes", "yes please", "save it"])
def test_education_invitation_cannot_approve_older_transaction_preview(stub_ai, monkeypatch, reply):
    original_coach = StubAIServiceClient.coach

    async def coach_with_education_invitation(self, request):
        response = await original_coach(self, request)
        if request.message == "Explain diversification.":
            answer = "Diversification spreads investment exposure. Would you like an example?"
            return CoachResponse(session_id=request.session_id, selected_agents=["investment_education"],
                answer=answer, agent_results=[{"agent": "investment_education", "summary": answer,
                    "rationale": [], "confidence": 1.0, "data": {}}],
                audit=response.audit, disclaimers=response.disclaimers)
        return response

    monkeypatch.setattr(StubAIServiceClient, "coach", coach_with_education_invitation)
    stub_ai.draft = {**record(txn("Chicken rice", 5, "2026-09-24")), "persistence_intent": "preview"}
    post_coach("cap-preview-invitation", "Prepare my chicken rice expense for review.")
    stub_ai.draft = None
    education = post_coach("cap-preview-invitation", "Explain diversification.")
    assert "Would you like an example?" in education["answer"]
    post_coach("cap-preview-invitation", reply)
    assert transactions_for("cap-preview-invitation") == []
    confirmed = post_coach("cap-preview-invitation", "confirm transaction")
    assert confirmed["audit"]["action_status"] == "saved"
    assert len(transactions_for("cap-preview-invitation")) == 1
    post_coach("cap-preview-invitation", "confirm transaction")
    assert len(transactions_for("cap-preview-invitation")) == 1


@pytest.mark.parametrize("interlude", ["unrelated", "not_spending", "query", "unresolved_query", "forecast"])
def test_coach_preview_survives_read_only_turn_before_confirmation(stub_ai: type[StubAIServiceClient], interlude):
    stub_ai.draft = {**record(txn("Chicken rice", 5, "2026-09-24")), "persistence_intent": "preview"}
    post_coach("cap-preview-continuity", "I spent $5 on chicken rice yesterday. Prepare it for review.")
    stub_ai.draft = {
        "unrelated": None,
        "not_spending": {"is_spending_request": False},
        "query": query("2026-09-24"),
        "unresolved_query": query(),
        "forecast": {"action": "forecast", "query_start": "2026-10-01", "query_end": "2026-10-31"},
    }[interlude]
    post_coach("cap-preview-continuity", "Explain a financial concept or answer my recorded-spending question.")
    assert transactions_for("cap-preview-continuity") == []
    confirmed = post_coach("cap-preview-continuity", "confirm")
    assert confirmed["audit"]["action_status"] == "saved"
    rows = transactions_for("cap-preview-continuity")
    assert len(rows) == 1 and rows[0]["amount"]["amount"] == 5


def test_coach_preview_amendment_requires_fresh_confirmation(stub_ai: type[StubAIServiceClient]):
    stub_ai.draft = {**record(txn("Chicken rice", 5, "2026-09-24")), "persistence_intent": "preview"}
    post_coach("cap-preview-correction", "I spent $5 on chicken rice yesterday. Prepare it for review.")
    stub_ai.draft = record(txn("Chicken rice", 7, "2026-09-24"))
    corrected = post_coach("cap-preview-correction", "The amount was 7.")
    assert corrected["audit"]["action_status"] == "preview"
    assert "7.00" in corrected["answer"]
    assert transactions_for("cap-preview-correction") == []
    confirmed = post_coach("cap-preview-correction", "confirm")
    assert confirmed["audit"]["action_status"] == "saved"
    rows = transactions_for("cap-preview-correction")
    assert len(rows) == 1 and rows[0]["amount"]["amount"] == 7


def test_named_edit_previews_then_confirm_applies(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Anniversary Dinner", 500.0, "2026-09-20"))
    post_coach("cap-e1", "i spent 500 on anniversary dinner on 20 sep")
    before = transactions_for("cap-e1")[0]
    body = post_coach("cap-e1", "change my anniversary dinner spending to 988")
    assert body["audit"]["action_status"] == "preview"
    answer = body["answer"]
    assert "500.00" in answer
    assert "988.00" in answer
    assert "confirm" in answer.lower()
    assert len(transactions_for("cap-e1")) == 1
    saved = post_coach("cap-e1", "confirm")
    assert saved["audit"]["action_status"] == "saved"
    assert "988.00" in saved["answer"]
    assert "updated" in saved["answer"].lower()
    txns = transactions_for("cap-e1")
    assert len(txns) == 1
    assert txns[0]["amount"]["amount"] == 988.0
    assert txns[0]["description"] == before["description"]
    assert txns[0]["occurred_on"] == before["occurred_on"]


def test_named_edit_cancel_changes_nothing(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Anniversary Dinner", 500.0, "2026-09-20"))
    post_coach("cap-e2", "i spent 500 on anniversary dinner on 20 sep")
    post_coach("cap-e2", "change my anniversary dinner spending to 988")
    body = post_coach("cap-e2", "cancel")
    assert body["audit"]["action_status"] == "cancelled"
    assert "nothing was changed" in body["answer"].lower()
    assert transactions_for("cap-e2")[0]["amount"]["amount"] == 500.0


def test_named_edit_ambiguous_date_disambiguates(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.drafts = [record(txn("Dinner", 50.0)), record(txn("Dinner", 80.0, "2026-09-21"))]
    post_coach("cap-e3", "i spent 50 on dinner yesterday")
    post_coach("cap-e3", "i spent 80 on dinner on 21/9")
    body = post_coach("cap-e3", "edit the dinner amount to 70")
    assert body["audit"]["action_status"] == "needs_input"
    assert "which" in body["answer"].lower()
    preview = post_coach("cap-e3", "the 21 sep one")
    assert "confirm" in preview["answer"].lower()
    post_coach("cap-e3", "confirm")
    txns = transactions_for("cap-e3")
    updated = next(item for item in txns if item["occurred_on"] == "2026-09-21")
    assert updated["amount"]["amount"] == 70.0
    untouched = next(item for item in txns if item["occurred_on"] == "2026-09-24")
    assert untouched["amount"]["amount"] == 50.0


def test_named_edit_no_match_reports_not_found(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Kopi", 5.0))
    post_coach("cap-e4", "i spent 5 on kopi today")
    body = post_coach("cap-e4", "change my concert ticket spending to 300")
    assert "couldn't find" in body["answer"].lower()
    txns = transactions_for("cap-e4")
    assert len(txns) == 1
    assert txns[0]["amount"]["amount"] == 5.0


def test_named_edit_recomputes_budget_flag(stub_ai: type[StubAIServiceClient]) -> None:
    set_budget("cap-e5", {"food": 100.0})
    stub_ai.draft = record(txn("Chicken Rice", 90.0))
    post_coach("cap-e5", "i spent 90 on chicken rice today")
    post_coach("cap-e5", "change my chicken rice spending to 120")
    saved = post_coach("cap-e5", "confirm")
    lowered = saved["answer"].lower()
    assert "updated" in lowered
    assert "over" in lowered
    assert "120.00" in saved["answer"]


def test_named_edit_polite_two_sentence_request(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Anniversary Dinner", 500.0, "2026-09-20", booking=True))
    post_coach("cap-e6", "i have booked for a 500 anniversary dinner on 20 Sep")
    body = post_coach(
        "cap-e6",
        "i have a transaction for Anniversary Dinner. "
        "Would you be able to edit the spending to 988",
    )
    answer = body["answer"]
    assert "500.00" in answer
    assert "988.00" in answer
    assert "confirm" in answer.lower()
    post_coach("cap-e6", "confirm")
    txns = transactions_for("cap-e6")
    assert len(txns) == 1
    assert txns[0]["amount"]["amount"] == 988.0


def test_named_edit_request_without_name_asks(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.drafts = [record(txn("Dinner", 50.0))]
    post_coach("cap-e7", "i spent 50 on dinner yesterday")
    body = post_coach("cap-e7", "would you be able to edit the spending to 988")
    assert "couldn't find" in body["answer"].lower()
    assert len(transactions_for("cap-e7")) == 1


# --- named transaction delete with confirmation ------------------------------------


def test_named_delete_previews_then_confirm_deletes(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = record(txn("Anniversary Dinner", 500.0, "2026-09-20"))
    post_coach("cap-d1", "i spent 500 on anniversary dinner on 20 sep")
    body = post_coach("cap-d1", "delete my anniversary dinner transaction")
    assert body["audit"]["action_status"] == "preview"
    answer = body["answer"]
    assert "500.00" in answer
    assert "confirm" in answer.lower()
    assert len(transactions_for("cap-d1")) == 1
    removed = post_coach("cap-d1", "confirm")
    assert removed["audit"]["action_status"] == "deleted"
    assert "deleted" in removed["answer"].lower()
    assert transactions_for("cap-d1") == []


def test_named_delete_cancel_keeps_transaction(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [record(txn("Anniversary Dinner", 500.0, "2026-09-20"))]
    post_coach("cap-d2", "i spent 500 on anniversary dinner on 20 sep")
    post_coach("cap-d2", "delete my anniversary dinner transaction")
    body = post_coach("cap-d2", "cancel")
    assert body["audit"]["action_status"] == "cancelled"
    assert "nothing was deleted" in body["answer"].lower()
    assert len(transactions_for("cap-d2")) == 1


def test_named_delete_no_match_reports_not_found(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.draft = record(txn("Kopi", 5.0))
    post_coach("cap-d3", "i spent 5 on kopi today")
    body = post_coach("cap-d3", "delete my concert ticket transaction")
    assert "couldn't find" in body["answer"].lower()
    assert len(transactions_for("cap-d3")) == 1


def test_named_delete_ambiguous_date_disambiguates(
    stub_ai: type[StubAIServiceClient],
) -> None:
    stub_ai.drafts = [record(txn("Dinner", 50.0)), record(txn("Dinner", 80.0, "2026-09-21"))]
    post_coach("cap-d4", "i spent 50 on dinner yesterday")
    post_coach("cap-d4", "i spent 80 on dinner on 21/9")
    body = post_coach("cap-d4", "delete the dinner transaction")
    assert "which" in body["answer"].lower()
    preview = post_coach("cap-d4", "the 21 sep one")
    assert "confirm" in preview["answer"].lower()
    post_coach("cap-d4", "confirm")
    txns = transactions_for("cap-d4")
    assert len(txns) == 1
    assert txns[0]["amount"]["amount"] == 50.0


def test_named_delete_with_date_filter(stub_ai: type[StubAIServiceClient]) -> None:
    def add_on(when: str) -> None:
        response = client.post(
            "/api/users/cap-d5/transactions",
            headers=HEADERS,
            json={
                "description": "Lunch",
                "category": "food",
                "amount": {"currency": "SGD", "amount": 12.0},
                "occurred_on": when,
            },
        )
        assert response.status_code == 201, response.text

    add_on("2026-09-28")
    add_on("2026-10-01")
    body = post_coach("cap-d5", "can you delete for me Lunch on the 1st October?")
    assert stub_ai.last_request is None
    answer = body["answer"]
    assert "confirm" in answer.lower()
    assert "1 Oct 2026" in answer
    post_coach("cap-d5", "confirm")
    txns = transactions_for("cap-d5")
    assert [item["occurred_on"] for item in txns] == ["2026-09-28"]


def test_named_edit_with_date_filter(stub_ai: type[StubAIServiceClient]) -> None:
    response = client.post(
        "/api/users/cap-d6/transactions",
        headers=HEADERS,
        json={
            "description": "Lunch",
            "category": "food",
            "amount": {"currency": "SGD", "amount": 12.0},
            "occurred_on": "2026-10-01",
        },
    )
    assert response.status_code == 201, response.text
    body = post_coach("cap-d6", "change my Lunch on 1st October to 25")
    assert "confirm" in body["answer"].lower()
    assert "25.00" in body["answer"]
    post_coach("cap-d6", "confirm")
    txns = transactions_for("cap-d6")
    assert txns[0]["amount"]["amount"] == 25.0


def test_named_delete_disambiguate_by_description_and_date(
    stub_ai: type[StubAIServiceClient],
) -> None:
    def add(description: str, amount: float, when: str) -> None:
        response = client.post(
            "/api/users/cap-d7/transactions",
            headers=HEADERS,
            json={
                "description": description,
                "category": "food",
                "amount": {"currency": "SGD", "amount": amount},
                "occurred_on": when,
            },
        )
        assert response.status_code == 201, response.text

    add("Lunch", 10.0, "2026-10-02")
    add("Colleague Farewell Lunch", 48.0, "2026-10-02")
    add("Lunch", 10.0, "2026-09-30")
    body = post_coach("cap-d7", "can you delete the transaction Lunch")
    assert "which" in body["answer"].lower()
    preview = post_coach("cap-d7", "Lunch on 2 Oct")
    assert "confirm" in preview["answer"].lower()
    assert "48.00" not in preview["answer"]
    assert "Saved" not in preview["answer"]
    post_coach("cap-d7", "confirm")
    txns = transactions_for("cap-d7")
    assert sorted((item["description"], item["occurred_on"]) for item in txns) == [
        ("Colleague Farewell Lunch", "2026-10-02"),
        ("Lunch", "2026-09-30"),
    ]


def test_pick_attempt_by_full_description_only(
    stub_ai: type[StubAIServiceClient],
) -> None:
    response = client.post(
        "/api/users/cap-d8/transactions",
        headers=HEADERS,
        json={
            "description": "Colleague Farewell Lunch",
            "category": "food",
            "amount": {"currency": "SGD", "amount": 48.0},
            "occurred_on": "2026-10-02",
        },
    )
    assert response.status_code == 201, response.text
    response = client.post(
        "/api/users/cap-d8/transactions",
        headers=HEADERS,
        json={
            "description": "Team Lunch",
            "category": "food",
            "amount": {"currency": "SGD", "amount": 12.0},
            "occurred_on": "2026-09-30",
        },
    )
    assert response.status_code == 201, response.text
    post_coach("cap-d8", "delete the lunch transaction")
    body = post_coach("cap-d8", "Colleague Farewell Lunch")
    assert "confirm" in body["answer"].lower()
    assert "48.00" in body["answer"]
    assert "Saved" not in body["answer"]
    assert len(transactions_for("cap-d8")) == 2


# --- cross-user isolation -------------------------------------------------------


def test_snapshot_contains_only_requesting_users_transactions(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("iso-a", "Own Kopi", "food", 2.0)
    add_transaction("iso-b", "Secret Lunch", "food", 42.0)
    post_coach("iso-a", "how are you?", session_id="iso-s1")
    assert stub_ai.last_request is not None
    descriptions = [item.description for item in stub_ai.last_request.snapshot.recent_transactions]
    assert "Secret Lunch" not in descriptions
    assert any("Kopi" in description for description in descriptions)


def test_client_supplied_snapshot_is_replaced_when_db_snapshot_exists(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("iso-c", "Real Transaction", "food", 5.0)
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={
            "user_id": "iso-c",
            "session_id": "iso-s2",
            "message": "hello",
            "snapshot": {
                "recent_transactions": [
                    {
                        "description": "Injected Transaction",
                        "category": "food",
                        "amount": {"currency": "SGD", "amount": 999.0},
                        "occurred_on": "2026-09-21",
                    }
                ]
            },
        },
    )
    assert response.status_code == 200
    assert stub_ai.last_request is not None
    descriptions = [item.description for item in stub_ai.last_request.snapshot.recent_transactions]
    assert "Injected Transaction" not in descriptions
    assert "Real Transaction" in descriptions


def test_date_spending_query_only_sees_own_transactions(
    stub_ai: type[StubAIServiceClient],
) -> None:
    add_transaction("iso-d", "Secret Dinner", "food", 50.0)
    stub_ai.draft = query(None)
    body = post_coach("iso-e", "how much did I spend on 20/9?", session_id="iso-s3")
    assert "no matching" in body["answer"].lower()
    assert "Secret Dinner" not in body["answer"]


def test_capture_saves_only_for_requesting_user(stub_ai: type[StubAIServiceClient]) -> None:
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    add_transaction("iso-f2", "Existing Item", "other", 9.0)
    post_coach("iso-f", "i spent $5 on chicken rice today", session_id="iso-s4")
    own = transactions_for("iso-f")
    assert len(own) == 1
    assert own[0]["description"] == "Chicken Rice"
    other = transactions_for("iso-f2")
    assert [item["description"] for item in other] == ["Existing Item"]


def test_budget_status_query_only_uses_own_spending(stub_ai: type[StubAIServiceClient]) -> None:
    add_transaction("iso-g2", "Secret Splurge", "shopping", 9999.0)
    body = post_coach("iso-g", "is my spending okay this month?", session_id="iso-s5")
    assert stub_ai.last_request is not None
    assert "Secret Splurge" not in body["answer"]


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
    stub_ai.draft = record(txn("Chicken Rice", 5.0))
    caplog.set_level("INFO", logger="service.calls")
    post_coach("cap-u12", "i spent $5 on chicken rice today")
    events = _added_events(caplog)
    assert len(events) == 1
    assert events[0]["source"] == "coach_capture"
    assert events[0]["category"] == "food"
    assert "amount" not in events[0]
