"""Exact provider counting recovers only before inference, within both deadlines."""
import logging
from types import SimpleNamespace

import httpx
import openai
import pytest
from test_model_token_reservations import ARGS, Responses, gateway

from app.core.config import Settings
from app.models import gateway as module
from app.models.gateway import ModelGatewayError, OpenAIModelGateway


class CounterResponses(Responses):
    def __init__(self, failures):
        super().__init__()
        self.failures = list(failures)

    def count(self, **kwargs):
        self.count_requests.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return SimpleNamespace(input_tokens=self.input_count)


def timeout():
    return openai.APITimeoutError(request=httpx.Request("POST", "https://example.test"))


def test_transient_counter_failure_recovers_exact_reservation_before_single_generation():
    responses = CounterResponses([timeout()])
    model = gateway(responses, 80000)
    token = model.bind_trace("counter-recovery")
    try:
        assert model.generate(**ARGS)
        assert len(responses.count_requests) == 2
        assert [item["timeout"] for item in responses.count_requests] == [3.0, 5.0]
        assert len(responses.generation_requests) == 1
        assert model.snapshot("counter-recovery")[0]["reserved_tokens"] == 2000
        assert len(model.snapshot("counter-recovery")) == 1
    finally:
        model.reset_trace(token)


def test_exhausted_counter_has_no_inference_or_private_exception(caplog):
    caplog.set_level(logging.INFO)
    responses = CounterResponses([timeout(), timeout()])
    model = OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=responses))
    with pytest.raises(ModelGatewayError) as captured:
        model.count_input_tokens(**{key: value for key, value in ARGS.items() if key != "temperature"})
    assert captured.value.code == "MODEL_INPUT_TOKEN_COUNT_UNAVAILABLE"
    assert captured.value.__cause__ is None and captured.value.__suppress_context__
    assert len(responses.count_requests) == 2 and not responses.generation_requests
    assert "OPENAI_TIMEOUT" in caplog.text
    assert "example.test" not in caplog.text


def test_permission_failure_never_retries_or_logs_provider_content(caplog):
    caplog.set_level(logging.INFO)
    error = openai.PermissionDeniedError("PRIVATE-KEY", response=httpx.Response(403,
        request=httpx.Request("POST", "https://example.test")), body={"message": "PRIVATE-BODY"})
    responses = CounterResponses([error])
    model = OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=responses))
    with pytest.raises(ModelGatewayError):
        model.count_input_tokens(system_prompt="PROMPT_ID: router", user_prompt="{}", max_tokens=100)
    assert len(responses.count_requests) == 1 and not responses.generation_requests
    assert "OPENAI_ACCESS_DENIED" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_counter_retry_uses_recomputed_workflow_and_local_deadlines(monkeypatch):
    responses = CounterResponses([timeout()])
    clocks = iter([0, 0, 2.5])
    deadlines = iter([20, 1.25, 1.25])
    monkeypatch.setattr(module, "perf_counter", lambda: next(clocks))
    monkeypatch.setattr(module, "check_deadline", lambda component: next(deadlines))
    # Ignore tracing decorator clocks; count_input_tokens owns the budget clocks.
    model = OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=responses))
    assert OpenAIModelGateway.count_input_tokens.__wrapped__(model,
        system_prompt="PROMPT_ID: router", user_prompt="{}", max_tokens=100, timeout_seconds=4) == 1000
    assert [item["timeout"] for item in responses.count_requests] == [3.0, 1.25]


def test_exhausted_local_count_deadline_prevents_retry(monkeypatch):
    responses = CounterResponses([timeout()])
    clocks = iter([0, 0, 8.01])
    monkeypatch.setattr(module, "perf_counter", lambda: next(clocks))
    model = OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=responses))
    with pytest.raises(ModelGatewayError):
        OpenAIModelGateway.count_input_tokens.__wrapped__(model,
            system_prompt="PROMPT_ID: router", user_prompt="{}", max_tokens=100)
    assert len(responses.count_requests) == 1
