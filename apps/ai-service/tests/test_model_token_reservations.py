from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Event
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.gateway import ModelGatewayError, OpenAIModelGateway, TracingModelGateway


class Responses:
    def __init__(self, input_count=1000, *, wait=False):
        self.input_count, self.wait = input_count, wait
        self.started, self.release = Event(), Event()
        self.count_requests, self.generation_requests = [], []
        self.input_tokens = SimpleNamespace(count=self.count)

    def count(self, **kwargs):
        self.count_requests.append(kwargs)
        return SimpleNamespace(input_tokens=self.input_count)

    def create(self, **kwargs):
        self.generation_requests.append(kwargs)
        self.started.set()
        if self.wait:
            assert self.release.wait(5)
        return SimpleNamespace(status="completed", output_text='{"answer":"ok"}',
            usage=SimpleNamespace(input_tokens=self.input_count, output_tokens=100))


def gateway(responses, limit):
    config = Settings(_env_file=None, MODEL_PROVIDER="openai", MAX_MODEL_TOKENS_PER_RUN=limit)
    return TracingModelGateway(OpenAIModelGateway(config,
        client=SimpleNamespace(responses=responses)), config)


ARGS = {"system_prompt": "PROMPT_ID: test", "user_prompt": "Explain budgets.",
        "temperature": 0, "max_tokens": 1000}


def test_oversized_input_is_refused_before_inference():
    responses = Responses(input_count=80000)
    model = gateway(responses, 80000)
    token = model.bind_trace("large-input")
    try:
        with pytest.raises(ModelGatewayError) as failure:
            model.generate(**ARGS)
        assert failure.value.code == "MODEL_TOKEN_BUDGET_EXCEEDED"
        assert not responses.generation_requests
        assert responses.count_requests[0]["text"] == {"format": {"type": "json_object"}}
    finally:
        model.reset_trace(token)


def test_parallel_calls_cannot_spend_the_same_remaining_budget():
    responses = Responses(wait=True)
    model = gateway(responses, 3000)
    token = model.bind_trace("parallel-reservations")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(copy_context().run, model.generate, **ARGS)
            assert responses.started.wait(5)
            second = pool.submit(copy_context().run, model.generate, **ARGS)
            try:
                with pytest.raises(ModelGatewayError) as failure:
                    second.result(timeout=5)
                assert failure.value.code == "MODEL_TOKEN_BUDGET_EXCEEDED"
            finally:
                responses.release.set()
            assert first.result(timeout=5) == '{"answer":"ok"}'
        assert len(responses.generation_requests) == 1
        calls = model.snapshot("parallel-reservations")
        assert calls[0]["reserved_tokens"] == 2000
        assert calls[0]["total_tokens"] == 1100
        responses.wait = False
        # Actual usage reconciles the first reservation; an 800-token output
        # cap now fits exactly in the remaining 1900 tokens.
        assert model.generate(**{**ARGS, "max_tokens": 800})
        for name in ("model", "instructions", "input", "reasoning", "text"):
            assert responses.count_requests[-1][name] == responses.generation_requests[-1][name]
    finally:
        responses.release.set()
        model.reset_trace(token)


@pytest.mark.parametrize("invalid", [None, -1, True])
def test_invalid_provider_count_fails_closed_without_inference(invalid):
    responses = Responses(input_count=invalid)
    model = gateway(responses, 80000)
    token = model.bind_trace("invalid-count")
    try:
        with pytest.raises(ModelGatewayError) as failure:
            model.generate(**ARGS)
        assert failure.value.code == "MODEL_INPUT_TOKEN_COUNT_UNAVAILABLE"
        assert not responses.generation_requests
    finally:
        model.reset_trace(token)
