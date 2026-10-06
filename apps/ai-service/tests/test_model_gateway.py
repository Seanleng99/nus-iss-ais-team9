import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.gateway import (
    BedrockModelGateway,
    LocalFixtureModelGateway,
    ModelGatewayError,
    ModelGeneration,
    OpenAIModelGateway,
    TracingModelGateway,
)


class StubBedrockClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.request: dict | None = None

    def converse(self, **kwargs) -> dict:
        self.request = kwargs
        return self.response


class UsageGateway:
    def __init__(self, total_tokens: int) -> None:
        self.total_tokens = total_tokens

    def generate(self, **kwargs) -> str:
        del kwargs
        return ModelGeneration(
            "ok",
            usage={
                "inputTokens": self.total_tokens - 500,
                "outputTokens": 500,
                "totalTokens": self.total_tokens,
            },
        )


def test_real_provider_unknown_usage_prevents_further_model_spending():
    class TimedOutGateway:
        attempts = 0

        def generate(self, **kwargs):
            self.attempts += 1
            raise ModelGatewayError("Timed out.", code="OPENAI_TIMEOUT")

    delegate = TimedOutGateway()
    gateway = TracingModelGateway(delegate, Settings(MODEL_PROVIDER="openai", _env_file=None))
    token = gateway.bind_trace("unknown-usage")
    try:
        with pytest.raises(ModelGatewayError) as initial:
            gateway.generate(system_prompt="PROMPT_ID: agent_investment_education", user_prompt="{}", temperature=0, max_tokens=100)
        assert initial.value.code == "OPENAI_TIMEOUT"
        with pytest.raises(ModelGatewayError) as retry:
            gateway.generate(system_prompt="PROMPT_ID: education_query_planner", user_prompt="{}", temperature=0, max_tokens=100)
        assert retry.value.code == "MODEL_USAGE_UNKNOWN"
        assert delegate.attempts == 1
        assert len(gateway.snapshot("unknown-usage")) == 1
        assert gateway.snapshot("unknown-usage")[0]["total_tokens"] is None
    finally:
        gateway.reset_trace(token)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [({}, True), ({"contextual_financial_findings": ["ambiguous wording"]}, False)],
)
def test_local_fixture_verdict_requires_no_contextual_financial_findings(
    payload, expected,
) -> None:
    result = json.loads(
        LocalFixtureModelGateway().generate(
            system_prompt="PROMPT_ID: risk_compliance",
            user_prompt=json.dumps(payload),
            temperature=0.1,
            max_tokens=100,
        )
    )

    assert result["financial_language_safe"] is expected


def test_bedrock_gateway_uses_converse_and_inference_controls() -> None:
    client = StubBedrockClient(
        {"output": {"message": {"content": [{"text": "{\"answer\":\"ok\"}"}]}}}
    )
    gateway = BedrockModelGateway(Settings(MODEL_ID="apac.amazon.nova-lite-v1:0"), client=client)
    result = gateway.generate(
        system_prompt="system",
        user_prompt="user",
        temperature=0.35,
        max_tokens=500,
    )
    assert result == '{"answer":"ok"}'
    assert client.request is not None
    assert client.request["modelId"] == "apac.amazon.nova-lite-v1:0"
    assert client.request["inferenceConfig"] == {"maxTokens": 500, "temperature": 0.35}


def test_bedrock_gateway_hides_invalid_provider_response() -> None:
    gateway = BedrockModelGateway(Settings(), client=StubBedrockClient({}))
    with pytest.raises(ModelGatewayError, match="configured model") as raised:
        gateway.generate(
            system_prompt="system",
            user_prompt="user",
            temperature=0.2,
            max_tokens=100,
        )

    assert raised.value.code == "BEDROCK_INVOCATION_FAILED"
    assert raised.value.component == "bedrock"


def test_bedrock_gateway_preserves_only_safe_provider_error_code() -> None:
    class ProviderFailure(Exception):
        def __init__(self, message: str) -> None:
            super().__init__(message)
            self.response = {"Error": {"Code": "AccessDeniedException"}}

    class FailingBedrockClient:
        def converse(self, **kwargs) -> dict:
            del kwargs
            raise ProviderFailure("provider detail that must not be logged")

    gateway = BedrockModelGateway(Settings(), client=FailingBedrockClient())
    with pytest.raises(ModelGatewayError) as raised:
        gateway.generate(
            system_prompt="system",
            user_prompt="user",
            temperature=0.2,
            max_tokens=100,
        )

    assert raised.value.code == "BEDROCK_ACCESSDENIEDEXCEPTION"
    assert "provider detail" not in str(raised.value)


def test_openai_gateway_uses_responses_without_storing_financial_prompts() -> None:
    class StubResponses:
        def __init__(self) -> None:
            self.request = None

        def create(self, **kwargs):
            self.request = kwargs
            return SimpleNamespace(
                status="completed",
                output_text='{"answer":"ok"}',
                usage=SimpleNamespace(input_tokens=123, output_tokens=45),
            )

    responses = StubResponses()
    gateway = OpenAIModelGateway(
        Settings(MODEL_ID="gpt-6-luna", MODEL_REASONING_EFFORT="low"),
        client=SimpleNamespace(responses=responses),
    )
    result = gateway.generate(
        system_prompt="system", user_prompt="user", temperature=0.35, max_tokens=1600
    )
    assert result == '{"answer":"ok"}'
    assert result.usage == {"inputTokens": 123, "outputTokens": 45, "totalTokens": 168}
    assert responses.request == {
        "model": "gpt-6-luna", "instructions": "system",
        "input": [
            {"role": "developer", "content": "Return one valid JSON object matching the required contract."},
            {"role": "user", "content": "user"},
        ],
        "reasoning": {"effort": "low"}, "max_output_tokens": 1600, "store": False,
        "text": {"format": {"type": "json_object"}},
    }


@pytest.mark.parametrize("status,code", [(None, "OPENAI_INVOCATION_FAILED"), (429, "OPENAI_RATE_LIMITED")])
def test_openai_gateway_hides_provider_errors_and_empty_responses(status, code) -> None:
    class FailingResponses:
        def create(self, **kwargs):
            error = RuntimeError("private provider details")
            error.status_code = status
            raise error

    gateway = OpenAIModelGateway(
        Settings(), client=SimpleNamespace(responses=FailingResponses())
    )
    with pytest.raises(ModelGatewayError) as error:
        gateway.generate(system_prompt="s", user_prompt="u", temperature=0.2, max_tokens=100)
    assert error.value.code == code
    assert "private provider details" not in str(error.value)


def test_default_model_token_budget_finishes_all_assessment_and_review_stages(monkeypatch) -> None:
    monkeypatch.delenv("MAX_MODEL_TOKENS_PER_RUN", raising=False)
    gateway = TracingModelGateway(UsageGateway(10_000), Settings(_env_file=None))
    token = gateway.bind_trace("full-reviewed-workflow")
    stages = ["education_query_planner", "education_answerability", "agent_investment_education",
              "synthesizer", "risk_compliance", "agent_investment_education", "synthesizer", "risk_compliance"]
    try:
        for component in stages:
            assert gateway.generate(system_prompt="PROMPT_ID: " + component, user_prompt="{}",
                                    temperature=0, max_tokens=500) == "ok"
        calls = gateway.snapshot("full-reviewed-workflow")
        assert [item["component"] for item in calls] == stages
        assert sum(item["total_tokens"] for item in calls) == 80_000
        assert all(item["status"] == "completed" for item in calls)
        with pytest.raises(ModelGatewayError) as exhausted:
            gateway.generate(system_prompt="PROMPT_ID: synthesizer", user_prompt="{}",
                             temperature=0, max_tokens=500)
        assert exhausted.value.code == "MODEL_TOKEN_BUDGET_EXCEEDED"
        assert len(gateway.snapshot("full-reviewed-workflow")) == len(stages)
    finally:
        gateway.reset_trace(token)
        gateway.clear("full-reviewed-workflow")


def test_tracing_gateway_allows_exact_model_token_budget() -> None:
    settings = Settings(MAX_MODEL_TOKENS_PER_RUN=20_000)
    gateway = TracingModelGateway(UsageGateway(10_000), settings)
    token = gateway.bind_trace("at-budget")

    try:
        for _ in range(2):
            result = gateway.generate(
                system_prompt="PROMPT_ID: test",
                user_prompt="{}",
                temperature=0.1,
                max_tokens=500,
            )
    finally:
        gateway.reset_trace(token)
        gateway.clear("at-budget")

    assert result == "ok"


def test_tracing_gateway_reports_model_token_budget_overrun() -> None:
    settings = Settings(MAX_MODEL_TOKENS_PER_RUN=20_000)
    gateway = TracingModelGateway(UsageGateway(10_001), settings)
    token = gateway.bind_trace("over-budget")

    try:
        gateway.generate(
            system_prompt="PROMPT_ID: test",
            user_prompt="{}",
            temperature=0.1,
            max_tokens=500,
        )
        with pytest.raises(ModelGatewayError) as raised:
            gateway.generate(
                system_prompt="PROMPT_ID: test",
                user_prompt="{}",
                temperature=0.1,
                max_tokens=500,
            )
    finally:
        gateway.reset_trace(token)
        gateway.clear("over-budget")

    assert raised.value.code == "MODEL_TOKEN_BUDGET_EXCEEDED"
    assert raised.value.component == "model_budget"


def test_exhausted_token_budget_rejects_next_call_before_provider_invocation() -> None:
    class CountingUsageGateway(UsageGateway):
        calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            return super().generate(**kwargs)

    delegate = CountingUsageGateway(20_000)
    gateway = TracingModelGateway(delegate, Settings(MAX_MODEL_TOKENS_PER_RUN=20_000))
    token = gateway.bind_trace("spent-budget")
    arguments = {"system_prompt": "PROMPT_ID: test", "user_prompt": "{}", "temperature": 0.2, "max_tokens": 500}
    try:
        assert gateway.generate(**arguments) == "ok"
        with pytest.raises(ModelGatewayError) as error:
            gateway.generate(**arguments)
        assert error.value.code == "MODEL_TOKEN_BUDGET_EXCEEDED"
        assert delegate.calls == 1
    finally:
        gateway.reset_trace(token)
        gateway.clear("spent-budget")
