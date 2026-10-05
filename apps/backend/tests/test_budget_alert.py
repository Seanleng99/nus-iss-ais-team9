from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app
from app.services.budget_alert import (
    build_status_reply,
    compute_budget_alert,
    parse_budget_status_query,
)

PERIOD = date(2026, 9, 1)

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
            audit={"source": "stub", "turn_decision": {
                "budget_status_query": request.message in {
                    "am I over budget?", "how am I doing with my spending this month?",
                },
            }},
        )


@pytest.fixture
def stub_ai() -> Iterator[type[StubAIServiceClient]]:
    app.dependency_overrides[get_ai_service_client] = StubAIServiceClient
    StubAIServiceClient.last_request = None
    try:
        yield StubAIServiceClient
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


def set_income(user_id: str, amount: float) -> None:
    response = client.put(
        f"/api/users/{user_id}/profile",
        headers=HEADERS,
        json={"monthly_income": {"currency": "SGD", "amount": amount}},
    )
    assert response.status_code == 200, response.text


def set_budget(user_id: str, categories: dict[str, float]) -> None:
    response = client.put(
        f"/api/users/{user_id}/budget",
        headers=HEADERS,
        json={
            "period_start": PERIOD.isoformat(),
            "categories": [
                {"category": category, "limit_amount": limit}
                for category, limit in categories.items()
            ],
        },
    )
    assert response.status_code == 200, response.text


def add_spending(user_id: str, category: str, amount: float, on: str = "2026-09-10") -> None:
    response = client.post(
        f"/api/users/{user_id}/transactions",
        headers=HEADERS,
        json={
            "description": f"{category} purchase",
            "category": category,
            "amount": {"currency": "SGD", "amount": amount},
            "occurred_on": on,
        },
    )
    assert response.status_code == 201, response.text


# --- compute_budget_alert thresholds ------------------------------------------


def test_no_alert_without_income_or_budget(db_session_factory) -> None:
    set_income("ba-none", 0.0)  # profile exists but no income
    with db_session_factory() as session:
        assert compute_budget_alert(session, "ba-none", PERIOD) is None


@pytest.mark.parametrize(
    ("spent", "expected_status"),
    [
        (799.99, None),
        (800.0, "approaching"),
        (999.0, "approaching"),
        (1000.0, "approaching"),
        (1000.01, "over"),
        (1500.0, "over"),
    ],
)
def test_income_usage_thresholds(
    db_session_factory, spent: float, expected_status: str | None
) -> None:
    user_id = f"ba-inc-{int(spent * 100)}"
    set_income(user_id, 1000.0)
    add_spending(user_id, "food", spent)
    with db_session_factory() as session:
        alert = compute_budget_alert(session, user_id, PERIOD)
    if expected_status is None:
        assert alert is None
    else:
        assert alert is not None
        assert alert.status == expected_status
        assert alert.over_income is (expected_status == "over")


def test_income_usage_percent_reported(db_session_factory) -> None:
    set_income("ba-pct", 1000.0)
    add_spending("ba-pct", "food", 850.0)
    with db_session_factory() as session:
        alert = compute_budget_alert(session, "ba-pct", PERIOD)
    assert alert is not None
    assert alert.status == "approaching"
    assert alert.income_usage_percent == pytest.approx(85.0)


def test_category_over_limit_flags_over(db_session_factory) -> None:
    set_income("ba-cat", 10000.0)
    set_budget("ba-cat", {"food": 100.0, "transport": 100.0})
    add_spending("ba-cat", "food", 120.0)
    with db_session_factory() as session:
        alert = compute_budget_alert(session, "ba-cat", PERIOD)
    assert alert is not None
    assert alert.status == "over"
    assert alert.over_budget is True
    assert [item.category for item in alert.categories_over] == ["food"]
    assert alert.categories_over[0].spent == pytest.approx(120.0)
    assert alert.categories_over[0].limit_amount == pytest.approx(100.0)


def test_total_budget_over_without_category_over(db_session_factory) -> None:
    set_income("ba-tot", 10000.0)
    set_budget("ba-tot", {"food": 100.0, "transport": 100.0})
    add_spending("ba-tot", "food", 90.0)
    add_spending("ba-tot", "transport", 110.0)
    with db_session_factory() as session:
        alert = compute_budget_alert(session, "ba-tot", PERIOD)
    # transport 110 > 100 is over on its own; total 200 == limit, not over.
    assert alert is not None
    assert alert.status == "over"
    assert [item.category for item in alert.categories_over] == ["transport"]


def test_categories_at_80_percent_listed_as_at_limit(db_session_factory) -> None:
    set_income("ba-warn", 10000.0)
    set_budget("ba-warn", {"food": 100.0, "fun": 100.0})
    add_spending("ba-warn", "food", 85.0)
    with db_session_factory() as session:
        alert = compute_budget_alert(session, "ba-warn", PERIOD)
    assert alert is not None
    assert alert.status == "approaching"
    assert [item.category for item in alert.categories_at_limit] == ["food"]


def test_amount_over_income_reported(db_session_factory) -> None:
    set_income("ba-amt", 1000.0)
    add_spending("ba-amt", "food", 1200.0)
    with db_session_factory() as session:
        alert = compute_budget_alert(session, "ba-amt", PERIOD)
    assert alert is not None
    assert alert.status == "over"
    assert alert.amount_over_income == pytest.approx(200.0)


# --- status reply text ----------------------------------------------------------


def test_status_reply_over_mentions_totals(db_session_factory) -> None:
    set_income("ba-rpl", 1000.0)
    add_spending("ba-rpl", "food", 1200.0)
    with db_session_factory() as session:
        reply = build_status_reply(session, "ba-rpl", PERIOD)
    lowered = reply.lower()
    assert "over" in lowered
    assert "1,200.00" in reply
    assert "1,000.00" in reply


def test_status_reply_on_track_when_ok(db_session_factory) -> None:
    set_income("ba-rplok", 1000.0)
    add_spending("ba-rplok", "food", 200.0)
    with db_session_factory() as session:
        reply = build_status_reply(session, "ba-rplok", PERIOD)
    assert "on track" in reply.lower()
    assert "200.00" in reply


def test_status_reply_without_data_guides_setup(db_session_factory) -> None:
    set_income("ba-rplno", 0.0)
    with db_session_factory() as session:
        reply = build_status_reply(session, "ba-rplno", PERIOD)
    lowered = reply.lower()
    assert "income" in lowered or "budget" in lowered


# --- query parsing ----------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "am I over budget?",
        "Am I overspending?",
        "how am I doing with my spending this month?",
        "is my spending ok?",
        "am I exceeding my income?",
        "have I gone over my budget?",
        "am I on track with my spending this month?",
        "is my spending too high?",
    ],
)
def test_parse_budget_status_query_matches(message: str) -> None:
    assert parse_budget_status_query(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "create a budget",
        "what is my budget?",
        "how much did I spend last month?",
        "i spent $5 on chicken rice yesterday",
        "how can I save more?",
        "review my spending patterns",
        "set my food budget to 500",
    ],
)
def test_parse_budget_status_query_non_matches(message: str) -> None:
    assert parse_budget_status_query(message) is False


# --- dashboard integration ---------------------------------------------------------


def test_dashboard_includes_budget_alert() -> None:
    set_income("ba-dash", 1000.0)
    add_spending("ba-dash", "food", 1100.0)
    response = client.get(
        "/api/users/ba-dash/dashboard",
        headers=HEADERS,
        params={"period_start": PERIOD.isoformat()},
    )
    assert response.status_code == 200, response.text
    alert = response.json()["budget_alert"]
    assert alert is not None
    assert alert["status"] == "over"
    assert alert["over_income"] is True


def test_dashboard_budget_alert_none_when_ok() -> None:
    set_income("ba-dash2", 1000.0)
    add_spending("ba-dash2", "food", 100.0)
    response = client.get(
        "/api/users/ba-dash2/dashboard",
        headers=HEADERS,
        params={"period_start": PERIOD.isoformat()},
    )
    assert response.status_code == 200, response.text
    assert response.json()["budget_alert"] is None


# --- coach chat interception ----------------------------------------------------------


def post_coach(user_id: str, message: str, session_id: str = "ba-s1") -> dict:
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": user_id, "session_id": session_id, "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_coach_over_budget_question_answered_locally(
    stub_ai: type[StubAIServiceClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import routes

    monkeypatch.setattr(routes, "_current_period_start", lambda: PERIOD)
    set_income("ba-chat", 1000.0)
    add_spending("ba-chat", "food", 1300.0)

    body = post_coach("ba-chat", "am I over budget?")
    assert stub_ai.last_request is not None
    lowered = body["answer"].lower()
    assert "over" in lowered
    assert "1,300.00" in body["answer"]


def test_coach_on_track_question_answered_locally(
    stub_ai: type[StubAIServiceClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import routes

    monkeypatch.setattr(routes, "_current_period_start", lambda: PERIOD)
    set_income("ba-chat2", 1000.0)
    add_spending("ba-chat2", "food", 200.0)

    body = post_coach("ba-chat2", "how am I doing with my spending this month?")
    assert stub_ai.last_request is not None
    assert "on track" in body["answer"].lower()


def test_coach_status_question_without_spending_data(
    stub_ai: type[StubAIServiceClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import routes

    monkeypatch.setattr(routes, "_current_period_start", lambda: PERIOD)
    body = post_coach("ba-chat3", "am I over budget?")
    assert stub_ai.last_request is not None
    lowered = body["answer"].lower()
    assert "income" in lowered or "budget" in lowered


def test_coach_other_budget_requests_still_go_to_ai(
    stub_ai: type[StubAIServiceClient],
) -> None:
    body = post_coach("ba-chat4", "create a budget for me")
    assert body["answer"] == "Stub guidance"
    assert stub_ai.last_request is not None
