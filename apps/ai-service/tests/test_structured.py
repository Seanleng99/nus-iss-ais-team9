import json

import pytest

from app.core.schemas import AgentNarrative
from app.models.gateway import ModelGatewayError
from app.models.structured import generate_structured_response


class ScriptedGateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict] = []

    def generate(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return next(self.responses)


def test_generate_structured_response_corrects_once_at_low_temperature() -> None:
    gateway = ScriptedGateway(
        [
            "not valid JSON",
            json.dumps(
                {
                    "summary": "Grounded explanation",
                    "rationale": ["Approved evidence"],
                    "confidence": 0.8,
                }
            ),
        ]
    )

    result = generate_structured_response(
        gateway,
        response_type=AgentNarrative,
        system_prompt="PROMPT_ID: agent_investment_education\nReturn JSON.",
        user_prompt="{}",
        temperature=0.35,
        max_tokens=800,
    )

    assert result.summary == "Grounded explanation"
    assert len(gateway.calls) == 2
    assert gateway.calls[1]["temperature"] == 0.1
    assert "CORRECTION:" in gateway.calls[1]["system_prompt"]
    assert gateway.calls[1]["system_prompt"].startswith(
        "PROMPT_ID: agent_investment_education"
    )


def test_generate_structured_response_fails_after_bounded_correction() -> None:
    gateway = ScriptedGateway(["invalid", "still invalid"])

    with pytest.raises(ModelGatewayError) as raised:
        generate_structured_response(
            gateway,
            response_type=AgentNarrative,
            system_prompt="PROMPT_ID: agent_budget\nReturn JSON.",
            user_prompt="{}",
            temperature=0.35,
            max_tokens=800,
        )

    assert raised.value.code == "INVALID_STRUCTURED_RESPONSE"
    assert len(gateway.calls) == 2
