import json

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class InvalidNarrativeGateway(LocalFixtureModelGateway):
    def __init__(self, component, repeat_invalid=False):
        self.component = component
        self.repeat_invalid = repeat_invalid
        self.target_calls = []

    def generate(self, **kwargs):
        response = super().generate(**kwargs)
        if kwargs["system_prompt"].splitlines()[0] == f"PROMPT_ID: {self.component}":
            self.target_calls.append(kwargs)
            if self.repeat_invalid or len(self.target_calls) == 1:
                body = json.loads(response)
                body["rationale"] = ["Calculated amount [source:invented-calculation]."]
                return json.dumps(body)
        return response


def handle(gateway, version):
    return AgentOrchestrator(config=Settings(
        MODEL_PROVIDER="local_fixture", PROMPT_SET_VERSION=version, MAX_TASK_ATTEMPTS=1,
    ), gateway=gateway).handle(CoachRequest(
        user_id="synthetic-narrative-test", session_id="synthetic-narrative-test",
        message="Explain this monthly budget.", requested_agents=["budget"],
        snapshot={"monthly_income": {"currency": "SGD", "amount": 4000}},
    ))


@pytest.mark.parametrize("component", ["agent_budget", "risk_compliance"])
@pytest.mark.parametrize("version", ["v6", "v7"])
def test_specialist_and_compliance_citations_correct_before_publication(component, version):
    gateway = InvalidNarrativeGateway(component)
    response = handle(gateway, version)
    assert not response.blocked
    assert len(gateway.target_calls) == 2
    assert "CORRECTION:" in gateway.target_calls[1]["system_prompt"]
    assert "invented-calculation" not in response.model_dump_json()
    assert "4000.00" in response.answer


@pytest.mark.parametrize("component", ["agent_budget", "risk_compliance"])
def test_twice_invalid_narrative_is_never_published(component):
    gateway = InvalidNarrativeGateway(component, repeat_invalid=True)
    with pytest.raises(ModelGatewayError) as raised:
        handle(gateway, "v6")
    assert raised.value.code == "UNAPPROVED_CITATION"
    assert len(gateway.target_calls) == 2
