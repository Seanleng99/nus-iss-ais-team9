import json
import logging
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from streamlit.runtime.scriptrunner_utils.exceptions import StopException
from streamlit.testing.v1 import AppTest

from client import BackendClient, build_request
from ui import auth, pages, state
from ui.telemetry import call_span, context_fields, trace_context

JOURNEY = "a" * 32


def events(caplog):
    return [
        json.loads(record.message) for record in caplog.records if record.name == "service.calls"
    ]


@pytest.fixture(autouse=True)
def trace_logs(caplog):
    caplog.set_level(logging.INFO, logger="service")


def test_http_operations_have_unique_contexts_and_private_route_templates(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])

    client = BackendClient(
        id_token="PRIVATE_TOKEN", journey_id=JOURNEY, transport=httpx.MockTransport(handler)
    )
    before = context_fields()
    client.get_chat_session("PRIVATE_PERSON", "PRIVATE_SESSION")
    client.list_chat_sessions("PRIVATE_PERSON")

    assert context_fields() == before
    correlations = [request.headers["X-Correlation-ID"] for request in requests]
    assert len(set(correlations)) == 2
    assert all(UUID(value) for value in correlations)
    for request in requests:
        assert request.headers["X-Journey-ID"] == JOURNEY
        assert request.headers["Authorization"] == "Bearer PRIVATE_TOKEN"
        assert request.headers["X-Caller-Method"] == "client.BackendClient._request"
        request_span = next(
            event
            for event in events(caplog)
            if event.get("span_id") == request.headers["X-Parent-Span-ID"]
            and event["event"] == "method.started"
        )
        assert request_span["caller_method"] in {
            "client.BackendClient.get_chat_session",
            "client.BackendClient.list_chat_sessions",
        }
        assert request_span["parent_span_id"]
    routes = [event["route"] for event in events(caplog) if "route" in event]
    assert "/api/users/{user_id}/chat-sessions/{session_id}" in routes
    assert "/api/users/{user_id}/chat-sessions" in routes
    assert not any(
        private in caplog.text for private in ["PRIVATE_TOKEN", "PRIVATE_PERSON", "PRIVATE_SESSION"]
    )
    client._request("GET", "/unknown/PRIVATE_PATH?raw=PRIVATE_QUERY")
    assert events(caplog)[-2]["route"] == "<unmatched>"
    assert "PRIVATE_PATH" not in caplog.text
    assert "PRIVATE_QUERY" not in caplog.text


def test_coach_operation_keeps_parent_relationships_and_safe_metadata(caplog):
    requests = []
    response = {
        "answer": "PRIVATE_ANSWER_98000",
        "selected_agents": ["budget", "PRIVATE_PERSON"],
        "blocked": False,
        "sources": [{"canonical_url": "https://private.example/?token=PRIVATE_TOKEN"}],
        "audit": {"trace_id": "trace-response-1", "private": "PRIVATE_AUDIT"},
        "PRIVATE_FIELD": "PRIVATE_VALUE",
    }

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    client = BackendClient(id_token="PRIVATE_TOKEN", transport=httpx.MockTransport(handler))
    before = context_fields()
    with (
        trace_context(correlation_id="outer-operation", journey_id=JOURNEY),
        call_span("ui.pages.coach_page"),
    ):
        parent = context_fields()
        payload = build_request("PRIVATE_PERSON", "PRIVATE_QUESTION", "PRIVATE_SESSION")
        assert client.ask_coach(payload) == response
        assert context_fields() == parent
    assert context_fields() == before
    starts = {
        event["method"]: event for event in events(caplog) if event["event"] == "method.started"
    }
    for method in ["client.build_request", "client.BackendClient.ask_coach"]:
        assert starts[method]["caller_method"] == "ui.pages.coach_page"
        assert starts[method]["parent_span_id"] == parent["span_id"]
    assert (
        starts["client.BackendClient._request"]["parent_span_id"]
        == starts["client.BackendClient.ask_coach"]["span_id"]
    )
    assert requests[0].headers["X-Correlation-ID"] == "outer-operation"
    assert requests[0].headers["X-Journey-ID"] == JOURNEY
    assert json.loads(requests[0].content) == payload
    accepted = next(event for event in events(caplog) if event["event"] == "http.response_accepted")
    assert accepted["trace_id"] == "trace-response-1"
    assert accepted["selected_agents"] == ["budget"]
    assert accepted["blocked"] is False
    assert accepted["source_count"] == 1
    assert accepted["output_characters"] == len(response["answer"])
    assert accepted["response_fields"] == [
        "selected_agents",
        "answer",
        "sources",
        "audit",
        "blocked",
    ]
    assert "PRIVATE_" not in caplog.text
    assert "private.example" not in caplog.text


@pytest.mark.parametrize("failure", ["http", "json", "transport"])
def test_failed_requests_reset_context_and_never_log_raw_errors(caplog, failure):
    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("PRIVATE_NETWORK_ERROR", request=request)
        if failure == "json":
            return httpx.Response(200, text="PRIVATE_INVALID_JSON")
        return httpx.Response(403, text="PRIVATE_SERVER_ERROR")

    client = BackendClient(transport=httpx.MockTransport(handler), journey_id=JOURNEY)
    before = context_fields()
    expected = {"http": httpx.HTTPStatusError, "json": ValueError, "transport": httpx.ConnectError}[
        failure
    ]
    with pytest.raises(expected):
        client.ask_coach({"message": "PRIVATE_QUESTION"})
    assert context_fields() == before
    failures = [event for event in events(caplog) if event["event"] == "method.failed"]
    assert failures
    assert failures[-1]["method"] == "client.BackendClient.ask_coach"
    assert all(event["correlation_id"] for event in failures)
    assert not any(event["event"] == "http.response_accepted" for event in events(caplog))
    assert "PRIVATE_" not in caplog.text


@pytest.mark.parametrize("status, expected", [(404, "not_found"), (204, "empty")])
def test_empty_http_responses_keep_existing_semantics(caplog, status, expected):
    client = BackendClient(transport=httpx.MockTransport(lambda request: httpx.Response(status)))
    assert client.get_profile("PRIVATE_PERSON") is None
    accepted = next(event for event in events(caplog) if event["event"] == "http.response_accepted")
    assert accepted["status_code"] == status
    assert accepted["status"] == expected


@pytest.mark.parametrize(
    "token,key,opt_in,expected",
    [
        (None, "automation", True, True),
        (None, "automation", False, False),
        ("oidc-token", "automation", True, False),
        (None, None, True, False),
    ],
)
def test_synthetic_flag_is_explicit_automation_only_and_coach_only(
    monkeypatch, token, key, opt_in, expected
):
    monkeypatch.delenv("BACKEND_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={})

    client = BackendClient(
        id_token=token,
        automation_api_key=key,
        synthetic_log=opt_in,
        transport=httpx.MockTransport(handler),
    )
    client.ask_coach({"message": "test"})
    client.list_profiles()
    assert requests[0].headers.get("X-Synthetic-Log") == ("true" if expected else None)
    assert "X-Synthetic-Log" not in requests[1].headers


class SessionState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class User(dict):
    is_logged_in = True

    def __init__(self):
        super().__init__(sub="PRIVATE_PERSON", iss="https://PRIVATE_ISSUER", exp=10**12)
        self.tokens = {"id": "PRIVATE_TOKEN"}


@pytest.fixture
def auth_ui(monkeypatch):
    def stop():
        raise StopException()

    ui = SimpleNamespace(
        user=User(),
        session_state=SessionState(),
        button=lambda *a, **k: False,
        title=lambda *a: None,
        caption=lambda *a: None,
        warning=lambda *a: None,
        error=lambda *a: None,
        login=stop,
        logout=stop,
        stop=stop,
    )
    monkeypatch.setenv("FRONTEND_AUTH_REQUIRED", "true")
    monkeypatch.setattr(auth, "st", ui)
    monkeypatch.setattr(state, "st", ui)
    return ui


def test_login_observation_deduplicates_and_identity_change_resets(auth_ui, caplog):
    auth.require_authenticated_user()
    journey = auth_ui.session_state.journey_id
    assert UUID(journey).version == 4
    client = state.get_client()
    assert client.journey_id == journey
    auth_ui.user.tokens["id"] = "PRIVATE_REFRESHED_TOKEN"
    auth.require_authenticated_user()
    assert auth_ui.session_state.journey_id == journey
    assert state.get_client() is not client
    assert state.get_client().journey_id == journey
    assert len([e for e in events(caplog) if e["event"] == "auth.session_authenticated"]) == 1

    auth_ui.session_state.coach_pending_render = {"trace_id": "old-trace"}
    auth_ui.session_state.active_user_id = "PRIVATE_PROFILE"
    auth_ui.user["sub"] = "PRIVATE_OTHER_PERSON"
    auth.require_authenticated_user()
    assert auth_ui.session_state.journey_id != journey
    assert "coach_pending_render" not in auth_ui.session_state
    assert "active_user_id" not in auth_ui.session_state
    assert state.get_client().journey_id == auth_ui.session_state.journey_id
    assert len([e for e in events(caplog) if e["event"] == "auth.session_authenticated"]) == 2
    assert context_fields() == {"correlation_id": None, "journey_id": None}
    assert "PRIVATE_" not in caplog.text


def test_login_request_is_logged_immediately_before_redirect(auth_ui, caplog):
    auth_ui.user.is_logged_in = False
    auth_ui.button = lambda *a, **k: True

    def login():
        assert events(caplog)[-1]["event"] == "auth.login_requested"
        assert events(caplog)[-1]["method"] == "streamlit.user_info.login"
        assert events(caplog)[-1]["journey_id"] is None
        raise StopException()

    auth_ui.login = login
    with pytest.raises(StopException):
        auth.require_authenticated_user()
    assert "journey_id" not in auth_ui.session_state
    assert context_fields() == {"correlation_id": None, "journey_id": None}
    assert not any(e["event"] == "method.failed" for e in events(caplog))


@pytest.mark.parametrize("reason", ["expired", "missing_token", "not_logged_in", "logout"])
def test_auth_exit_clears_journey_and_private_client_state(auth_ui, caplog, reason):
    auth.require_authenticated_user()
    state.get_client()
    journey = auth_ui.session_state.journey_id
    auth_ui.session_state.coach_pending_question = "PRIVATE_QUESTION"
    if reason == "expired":
        auth_ui.user["exp"] = 0
    elif reason == "missing_token":
        auth_ui.user.tokens = {}
    elif reason == "not_logged_in":
        auth_ui.user.is_logged_in = False
    with pytest.raises(StopException):
        auth.logout() if reason == "logout" else auth.require_authenticated_user()
    for key in [
        "journey_id",
        "backend_client",
        "backend_client_identity_token",
        "coach_pending_question",
    ]:
        assert key not in auth_ui.session_state
    lifecycle = {
        "expired": "auth.session_expired",
        "missing_token": "auth.identity_token_missing",
        "not_logged_in": "auth.session_ended",
        "logout": "auth.logout_requested",
    }[reason]
    event = next(event for event in events(caplog) if event["event"] == lifecycle)
    assert event["journey_id"] == journey
    if reason in {"missing_token", "not_logged_in"}:
        with pytest.raises(StopException):
            auth.require_authenticated_user()
        assert len([e for e in events(caplog) if e["event"] == lifecycle]) == 1
    assert "PRIVATE_" not in caplog.text
    assert context_fields() == {"correlation_id": None, "journey_id": None}


@pytest.mark.parametrize("defer_history", [False, True])
def test_app_rerun_renders_only_matching_reply_once(caplog, defer_history):
    requests = []
    messages = [
        {
            "role": "assistant",
            "content": "PRIVATE_OLD_ANSWER",
            "explanation": {"trace_id": "old-trace"},
        }
    ]
    new_trace = uuid4().hex
    hidden_reads = 0

    def handler(request):
        nonlocal hidden_reads
        requests.append(request)
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"preferred_language": "English"})
        if request.url.path == "/api/coach":
            question = json.loads(request.content)["message"]
            explanation = {"trace_id": new_trace, "selected_agents": ["budget"], "blocked": False}
            messages.extend(
                [
                    {"role": "user", "content": question},
                    {
                        "role": "assistant",
                        "content": "PRIVATE_NEW_ANSWER",
                        "sources": [],
                        "explanation": explanation,
                    },
                ]
            )
            hidden_reads = int(defer_history)
            return httpx.Response(
                200,
                json={
                    "answer": "PRIVATE_NEW_ANSWER",
                    "sources": [],
                    "audit": {"trace_id": new_trace},
                    "selected_agents": ["budget"],
                    "blocked": False,
                },
            )
        if request.url.path.endswith("/chat-sessions"):
            return httpx.Response(200, json=[{"id": "PRIVATE_SESSION", "title": "Saved chat"}])
        history = messages[:-2] if hidden_reads else messages
        hidden_reads = max(0, hidden_reads - 1)
        return httpx.Response(200, json={"messages": history})

    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = BackendClient(
        automation_api_key="PRIVATE_KEY", journey_id=JOURNEY, transport=httpx.MockTransport(handler)
    )
    app.session_state["journey_id"] = JOURNEY
    app.session_state["backend_client_journey_id"] = JOURNEY
    app.session_state["active_user_id"] = "PRIVATE_PERSON"
    app.run(timeout=30)
    assert not app.exception
    assert not any(event["event"] == "coach.response_rendered" for event in events(caplog))
    app.chat_input[0].set_value("PRIVATE_QUESTION").run(timeout=30)
    assert not app.exception
    accepted = next(
        event for event in events(caplog) if event["event"] == "coach.response_accepted"
    )
    if defer_history:
        assert not any(event["event"] == "coach.response_rendered" for event in events(caplog))
        record = app.session_state["coach_pending_render"]
        assert set(record) == {
            "correlation_id",
            "journey_id",
            "trace_id",
            "caller_method",
            "parent_span_id",
        }
        assert "PRIVATE_" not in json.dumps(record)
        app.run(timeout=30)
        assert not app.exception
    rendered = [event for event in events(caplog) if event["event"] == "coach.response_rendered"]
    assert len(rendered) == 1
    assert rendered[0]["trace_id"] == accepted["trace_id"] == new_trace
    assert rendered[0]["correlation_id"] == accepted["correlation_id"]
    assert rendered[0]["journey_id"] == JOURNEY
    assert rendered[0]["caller_method"] == "ui.pages.coach_page"
    assert rendered[0]["parent_span_id"] == accepted["span_id"]
    assert rendered[0]["selected_agents"] == ["budget"]
    assert rendered[0]["source_count"] == 0
    assert rendered[0]["output_characters"] == len("PRIVATE_NEW_ANSWER")
    assert rendered[0]["response_fields"] == ["sources", "role", "content", "explanation"]
    assert "PRIVATE_NEW_ANSWER" in [item.value for item in app.markdown]
    assert "coach_pending_render" not in app.session_state
    post_index = next(i for i, request in enumerate(requests) if request.url.path == "/api/coach")
    assert requests[post_index].headers["X-Correlation-ID"] == accepted["correlation_id"]
    assert "X-Synthetic-Log" not in requests[post_index].headers
    history_request = next(
        request
        for request in requests[post_index + 1 :]
        if request.url.path.endswith("PRIVATE_SESSION")
    )
    assert history_request.headers["X-Correlation-ID"] == accepted["correlation_id"]
    explanation_span = next(
        e for e in events(caplog) if e.get("method") == "ui.pages._render_coach_explanation"
    )
    assert explanation_span["parent_span_id"] == rendered[0]["span_id"]
    count = len(events(caplog))
    app.run(timeout=30)
    assert not any(
        e.get("method", "").startswith("ui.pages._render") for e in events(caplog)[count:]
    )
    assert "PRIVATE_" not in caplog.text


def test_render_failure_does_not_claim_reply_was_rendered(monkeypatch, caplog):
    def fail_markdown(content):
        raise RuntimeError("PRIVATE_RENDER_ERROR")

    monkeypatch.setattr(
        pages,
        "st",
        SimpleNamespace(
            chat_message=lambda *a, **k: nullcontext(),
            markdown=fail_markdown,
        ),
    )
    with trace_context(journey_id=JOURNEY), pytest.raises(RuntimeError):
        pages._render_coach_message({"role": "assistant", "content": "PRIVATE_ANSWER"})
    assert any(e["event"] == "method.failed" for e in events(caplog))
    assert not any(e["event"] == "coach.response_rendered" for e in events(caplog))
    assert "PRIVATE_" not in caplog.text


def test_sidebar_signout_calls_actual_logout_and_clears_journey(monkeypatch, caplog):
    monkeypatch.delenv("FRONTEND_AUTH_REQUIRED", raising=False)
    monkeypatch.setattr(auth, "signed_in_label", lambda: "Signed-in test")
    calls = []

    def logout():
        calls.append(True)
        raise StopException()

    monkeypatch.setattr(auth.st, "logout", logout)
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = SimpleNamespace(list_profiles=list)
    app.session_state["backend_client_journey_id"] = JOURNEY
    app.session_state["journey_id"] = JOURNEY
    app.run(timeout=30)
    next(button for button in app.sidebar.button if button.label == "Sign out").click().run(
        timeout=30
    )
    assert not app.exception
    assert calls == [True]
    assert "journey_id" not in app.session_state
    assert "backend_client" not in app.session_state
    event = next(e for e in events(caplog) if e["event"] == "auth.logout_requested")
    assert event["journey_id"] == JOURNEY
    assert event["method"] == "streamlit.user_info.logout"
