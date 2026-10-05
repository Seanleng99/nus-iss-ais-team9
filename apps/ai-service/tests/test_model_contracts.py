import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.core.schemas import AgentNarrative, RouterDecision
from app.models.contracts import output_format, structured_contract
from app.models.gateway import ModelGatewayError, OpenAIModelGateway
from app.models.structured import generate_structured_response


class Responses:
    def __init__(self, response=None):
        self.requests = []
        self.response = response or SimpleNamespace(
            status="completed", output_text=json.dumps({
                "summary": "An explanation", "rationale": ["Grounded calculation"], "confidence": 0.8,
            }), output=[], usage=SimpleNamespace(
                input_tokens=100, output_tokens=50,
                output_tokens_details=SimpleNamespace(reasoning_tokens=20),
            ),
        )

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


def test_first_provider_request_uses_schema_and_role_controls():
    client = Responses()
    gateway = OpenAIModelGateway(Settings(MODEL_ROLE_OVERRIDES={
        "agent_budget": {"model_id": "role-model", "reasoning_effort": "medium", "max_tokens": 2400},
    }), client=SimpleNamespace(responses=client))
    result = generate_structured_response(
        gateway, response_type=AgentNarrative, system_prompt="PROMPT_ID: agent_budget\nReturn JSON.",
        user_prompt="{}", temperature=0.3, max_tokens=800,
    )
    request = client.requests[0]
    assert result.summary == "An explanation"
    assert request["model"] == "role-model"
    assert request["reasoning"] == {"effort": "medium"}
    assert request["max_output_tokens"] == 2400
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert "temperature" not in request
    assert output_format() == {"type": "json_object"}


def test_nested_schema_is_closed_and_default_fields_are_required():
    with structured_contract(RouterDecision):
        schema = output_format()["schema"]
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
        assert "default" not in schema["properties"]["education_topics"]


def test_open_operations_map_keeps_its_schema_and_local_validation():
    class Operations(BaseModel):
        changes: dict[str, int]

    with structured_contract(Operations):
        contract = output_format()
        assert contract["strict"] is False
        assert contract["schema"]["properties"]["changes"]["additionalProperties"] == {"type": "integer"}


@pytest.mark.parametrize("status,reason,output,code", [
    ("incomplete", "max_output_tokens", [], "MODEL_OUTPUT_TOKEN_LIMIT"),
    ("incomplete", "content_filter", [], "MODEL_CONTENT_FILTERED"),
    ("completed", None, [SimpleNamespace(content=[SimpleNamespace(type="refusal")])], "MODEL_REFUSAL"),
    ("completed", None, [], "MODEL_RESPONSE_EMPTY"),
])
def test_provider_failure_reasons_remain_distinct(status, reason, output, code):
    response = SimpleNamespace(status=status, output_text="", output=output,
                               incomplete_details=SimpleNamespace(reason=reason))
    gateway = OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=Responses(response)))
    with pytest.raises(ModelGatewayError) as error:
        gateway.generate(system_prompt="PROMPT_ID: router", user_prompt="{}", temperature=0.1, max_tokens=800)
    assert error.value.code == code


def test_reasoning_usage_is_separate_from_visible_output():
    gateway = OpenAIModelGateway(Settings(), client=SimpleNamespace(responses=Responses()))
    result = gateway.generate(system_prompt="PROMPT_ID: router", user_prompt="{}", temperature=0.1, max_tokens=800)
    assert result.provider_metrics["reasoningTokens"] == 20
    assert result.usage["outputTokens"] == 50


def test_shared_env_file_loads_role_settings_without_rejecting_other_services(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        'MODEL_PROVIDER=local_fixture\nBACKEND_BASE_URL=http://localhost:8080\n'
        'MODEL_ROLE_OVERRIDES={"router":{"max_tokens":1000}}\n', encoding="utf-8",
    )
    settings = Settings(_env_file=path)
    assert settings.model_provider == "local_fixture"
    assert settings.model_policy("router", 1600).max_tokens == 1000


def test_unknown_role_override_still_fails_configuration_validation():
    with pytest.raises(ValueError, match="unknown model role"):
        Settings(MODEL_ROLE_OVERRIDES={"unknown_agent": {"max_tokens":1000}})
