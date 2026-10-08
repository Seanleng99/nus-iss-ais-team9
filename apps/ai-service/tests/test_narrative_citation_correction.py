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


def handle(gateway, ):
    return AgentOrchestrator(config=Settings(
        MODEL_PROVIDER="local_fixture",  MAX_TASK_ATTEMPTS=1,
    ), gateway=gateway).handle(CoachRequest(
        user_id="synthetic-narrative-test", session_id="synthetic-narrative-test",
        message="Explain this monthly budget.", requested_agents=["budget"],
        snapshot={"monthly_income": {"currency": "SGD", "amount": 4000}},
    ))


@pytest.mark.parametrize("component", ["agent_budget", "risk_compliance"])
def test_specialist_and_compliance_citations_correct_before_publication(component, ):
    gateway = InvalidNarrativeGateway(component)
    response = handle(gateway)
    assert not response.blocked
    assert len(gateway.target_calls) == 2
    assert "CORRECTION:" in gateway.target_calls[1]["system_prompt"]
    assert "invented-calculation" not in response.model_dump_json()
    assert "4000.00" in response.answer


@pytest.mark.parametrize("component", ["agent_budget", "risk_compliance"])
def test_twice_invalid_narrative_is_never_published(component):
    gateway = InvalidNarrativeGateway(component, repeat_invalid=True)
    if component == "risk_compliance":
        response = handle(gateway)
        assert response.blocked and "review failure" in response.answer
        assert "invented-calculation" not in response.model_dump_json()
        assert response.agent_results[-1].data["block_reasons"] == ["review_contract_unverified"]
        assert any(event["details"].get("error_code") == "UNAPPROVED_CITATION"
                   for event in response.audit["events"])
    else:
        with pytest.raises(ModelGatewayError) as raised:
            handle(gateway)
        assert raised.value.code == "UNAPPROVED_CITATION"
    assert len(gateway.target_calls) == 2
