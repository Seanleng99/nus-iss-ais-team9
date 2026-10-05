"""SDK failures expose safe actionable codes without serializing provider data."""

import logging
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.core.config import Settings
from app.core.schemas import AgentTask
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError, OpenAIModelGateway
from app.orchestrator import AgentOrchestrator

PRIVATE_MESSAGE = "private SDK message with sk-private-key and user@example.test"
PRIVATE_BODY = "private response body with financial details"


def sdk_status_error(status, error_class, *, code=None):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses", headers={"Authorization": "Bearer sk-private-key"})
    response = httpx.Response(status, request=request)
    return error_class(PRIVATE_MESSAGE, response=response, body={"code": code, "message": PRIVATE_BODY})


@pytest.mark.parametrize("status,error_class,provider_code,expected", [
    (400, openai.BadRequestError, None, "OPENAI_INVALID_REQUEST"),
    (401, openai.AuthenticationError, "invalid_api_key", "OPENAI_AUTHENTICATION_FAILED"),
    (403, openai.PermissionDeniedError, None, "OPENAI_ACCESS_DENIED"),
    (404, openai.NotFoundError, "model_not_found", "OPENAI_MODEL_UNAVAILABLE"),
    (422, openai.UnprocessableEntityError, None, "OPENAI_INVALID_REQUEST"),
    (429, openai.RateLimitError, "rate_limit_exceeded", "OPENAI_RATE_LIMITED"),
    (429, openai.RateLimitError, "insufficient_quota", "OPENAI_QUOTA_EXCEEDED"),
    (429, openai.RateLimitError, "billing_hard_limit_reached", "OPENAI_QUOTA_EXCEEDED"),
    (500, openai.InternalServerError, None, "OPENAI_SERVER_ERROR"),
    (503, openai.InternalServerError, None, "OPENAI_SERVER_ERROR"),
    (408, openai.APIStatusError, None, "OPENAI_TIMEOUT"),
    (418, openai.APIStatusError, "sk-private-key", "OPENAI_INVOCATION_FAILED"),
])
def test_typed_sdk_status_is_classified_without_private_details(status, error_class, provider_code, expected, caplog):
    caplog.set_level(logging.INFO)
    sdk_error = sdk_status_error(status, error_class, code=provider_code)

    class Responses:
        def create(self, **kwargs):
            raise sdk_error

    gateway = OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=Responses()))
    with pytest.raises(ModelGatewayError) as captured:
        gateway.generate(system_prompt="PROMPT_ID: router", user_prompt="{}", temperature=0, max_tokens=100)
    assert captured.value.code == expected
    assert captured.value.__cause__ is None and captured.value.__suppress_context__
    observed = str(captured.value) + caplog.text
    assert PRIVATE_MESSAGE not in observed and PRIVATE_BODY not in observed
    assert "sk-private-key" not in observed and "user@example.test" not in observed


@pytest.mark.parametrize("sdk_class,expected", [
    (openai.APIConnectionError, "OPENAI_CONNECTION_ERROR"),
    (openai.APITimeoutError, "OPENAI_TIMEOUT"),
])
def test_sdk_transport_class_is_classified_without_message(sdk_class, expected):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    sdk_error = sdk_class(request=request)

    class Responses:
        def create(self, **kwargs):
            raise sdk_error

    with pytest.raises(ModelGatewayError) as captured:
        OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=Responses())).generate(
            system_prompt="PROMPT_ID: router", user_prompt="{}", temperature=0, max_tokens=100)
    assert captured.value.code == expected


@pytest.mark.parametrize("code,retryable", [
    ("OPENAI_AUTHENTICATION_FAILED", False), ("OPENAI_ACCESS_DENIED", False),
    ("OPENAI_MODEL_UNAVAILABLE", False), ("OPENAI_INVALID_REQUEST", False),
    ("OPENAI_QUOTA_EXCEEDED", False), ("OPENAI_INVOCATION_FAILED", False),
    ("OPENAI_API_KEY_MISSING", False), ("INVALID_STRUCTURED_RESPONSE", False),
    ("OPENAI_CONNECTION_ERROR", True), ("OPENAI_TIMEOUT", True),
    ("OPENAI_SERVER_ERROR", True), ("OPENAI_RATE_LIMITED", True),
    ("MODEL_GATEWAY_ERROR", True),
])
def test_only_transient_openai_failures_and_generic_fixture_errors_retry(code, retryable):
    class Agent:
        def __init__(self):
            self.calls = 0

        def run_task(self, task):
            self.calls += 1
            raise ModelGatewayError("Safe failure.", code=code)

    agent = Agent()
    orchestrator = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture", MAX_TASK_ATTEMPTS=3,
                                                   RETRY_BACKOFF_SECONDS=0), gateway=LocalFixtureModelGateway())
    outcome, attempt, retries, _ = orchestrator._execute_task(AgentTask(agent="spending", sanitized_message="Summarize."), agent)
    assert agent.calls == attempt == (3 if retryable else 1)
    assert len(retries) == (2 if retryable else 0)
    assert outcome.retryable is retryable
