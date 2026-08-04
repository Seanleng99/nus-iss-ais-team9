import pytest

from app.core.config import Settings
from app.models.gateway import BedrockModelGateway, ModelGatewayError


class StubBedrockClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.request: dict | None = None

    def converse(self, **kwargs) -> dict:
        self.request = kwargs
        return self.response


def test_bedrock_gateway_uses_converse_and_inference_controls() -> None:
    client = StubBedrockClient(
        {"output": {"message": {"content": [{"text": "{\"answer\":\"ok\"}"}]}}}
    )
    gateway = BedrockModelGateway(Settings(), client=client)
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
    with pytest.raises(ModelGatewayError, match="configured model"):
        gateway.generate(
            system_prompt="system",
            user_prompt="user",
            temperature=0.2,
            max_tokens=100,
        )
