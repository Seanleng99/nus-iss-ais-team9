from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from language_fixtures import language_case

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.main import app

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
            audit={"source": "stub", "turn_decision": {
                "budget_status_query": request.message == "is my spending okay this month?",
            }},
        )


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


def post_coach(user_id: str, message: str, session_id: str = "ou-s1") -> dict:
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": user_id, "session_id": session_id, "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "message",
    [
        "would you be able to tell me demo4255 spendings for this month?",
        "demo4255's recorded spending this month?",
        "how much did sarah42 spend this month?",
        "what did mickey123 purchase yesterday?",
        "show me alice99's transactions",
        "tell me about bob77 expenses",
    ],
)
def test_other_user_data_query_is_refused_without_ai_call(
    stub_ai: type[StubAIServiceClient], message: str
) -> None:
    body = post_coach("benjamin", message)
    assert stub_ai.last_request is None
    lowered = body["answer"].lower()
    assert "your own" in lowered or "cannot" in lowered or "can't" in lowered
    assert "demo4255" not in lowered or "your own" in lowered


@pytest.mark.parametrize(
    "message",
    [
        "show me John's transactions",
        "list Mary's savings goals",
        "what are her goals?",
        "tell me my colleague's budget",
        "what is my friend's monthly spending?",
        "how much does my sister earn?",
        "how much did Sarah spend this month?",
        "show me someone else's goals",
        "what are other people's transactions",
        "show me another user's budget",
        language_case(
            "other_user_data_guard.test_named_or_related_third_party_query_is_refused_without_ai_call"
        ),
        language_case(
            "other_user_data_guard.test_named_or_related_third_party_query_is_refused_without_ai_call_2"
        ),
    ],
)
def test_named_or_related_third_party_query_is_refused_without_ai_call(
    stub_ai: type[StubAIServiceClient], message: str
) -> None:
    body = post_coach("benjamin", message)
    assert stub_ai.last_request is None
    assert (
        "another person" in body["answer"]
        or language_case(
            "other_user_data_guard.test_named_or_related_third_party_query_is_refused_without_ai_call_3"
        )
        in body["answer"]
    )


@pytest.mark.parametrize(
    "message",
    [
        "what did my friend spend on 21 Sep?",
        "is my colleague's spending okay this month?",
    ],
)
def test_third_party_query_is_refused_before_local_data_handlers(
    stub_ai: type[StubAIServiceClient], message: str
) -> None:
    body = post_coach("benjamin", message)
    assert stub_ai.last_request is None
    assert "another person" in body["answer"]


@pytest.mark.parametrize(
    "message",
    [
        (
            "create budget plan for October 2026 as below: food sgd600 travel sgd100 "
            "entertainment sgd200 rental sgd1200 utilities sgd200 others sgd500 take-home "
            "income is sgd5000, the above included all my expenses this is my budget plan"
        ),
        "show me this month's transactions",
        "show me October's spending",
        "what are my goals?",
        "I want to save for my daughter's education",
        "how do investors set their goals?",
        "how much did I spend at McDonald's this month?",
    ],
)
def test_own_or_general_requests_reach_ai(
    stub_ai: type[StubAIServiceClient], message: str
) -> None:
    body = post_coach("benjamin", message, session_id="ou-s3")
    assert stub_ai.last_request is not None
    assert "another person" not in body["answer"]


def test_self_name_query_falls_through_to_ai(stub_ai: type[StubAIServiceClient]) -> None:
    body = post_coach("demo4255", "tell me demo4255 spendings for this month?")
    assert stub_ai.last_request is not None
    assert body["answer"] == "Stub guidance"


@pytest.mark.parametrize(
    ("message", "expected_answer"),
    [
        ("review my spending", "Stub guidance"),
        ("what is my highest spending category?", "Stub guidance"),
        ("how much did I spend on 20/9?", "Stub guidance"),
        ("is my spending okay this month?", None),
    ],
)
def test_own_data_queries_are_not_blocked(
    stub_ai: type[StubAIServiceClient], message: str, expected_answer: str | None
) -> None:
    body = post_coach("benjamin", message, session_id="ou-s2")
    if expected_answer is not None:
        assert body["answer"] == expected_answer
        assert stub_ai.last_request is not None
    else:
        assert stub_ai.last_request is not None
