"""Exercise production task contracts with model choices, not fixture recognizers."""

import json

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class AssignedGateway(LocalFixtureModelGateway):
    def __init__(self, assignments):
        self.assignments = assignments
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            return json.dumps({"selected_agents": ["spending", "budget"],
                               "rationale": ["Two distinct requested tasks."],
                               "task_assignments": self.assignments})
        # Deliberately request any offered capability: isolation must happen before planning.
        if kwargs["system_prompt"].startswith("PROMPT_ID: dependency_planner"):
            payload = json.loads(kwargs["user_prompt"])
            requests = [{k: v for k, v in item.items() if k != "selection_guidance"}
                        for item in payload["allowed_requests"]]
            return json.dumps({"status": "needs_dependency" if requests else "ready", "requests": requests})
        return super().generate(**kwargs)


def test_independent_model_tasks_do_not_offer_spending_to_budget():
    message = "Inspect my purchases; teach me a budgeting method."
    gateway = AssignedGateway([
        {"agent": "spending", "question": "Inspect my purchases", "source_quotes": ["Inspect my purchases"]},
        {"agent": "budget", "question": "Teach me a budgeting method", "source_quotes": ["teach me a budgeting method"],
         "requires_spending": False},
    ])
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u", session_id="s", message=message, snapshot={
            "monthly_income": {"amount": 6500}, "period_start": "2026-10-01",
            "recent_transactions": [{"description": "Food", "category": "food", "amount": {"amount": 50},
                                     "occurred_on": "2026-10-02"}]}))
    assert not response.audit["dependency_edges"]
    budget_calls = [json.loads(call["user_prompt"]) for call in gateway.calls
                    if call["system_prompt"].startswith("PROMPT_ID: agent_budget")]
    assert budget_calls and "purchases" not in budget_calls[0]["message"].lower()


@pytest.mark.parametrize("assignments", [[], [
    {"agent": "budget", "question": "Invented task", "source_quotes": ["not in the question"]},
]])
def test_unattributed_or_incomplete_task_contract_is_rejected(assignments):
    with pytest.raises(ModelGatewayError, match="task_assignments"):
        AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=AssignedGateway(assignments)).handle(
            CoachRequest(user_id="u", session_id="s", message="Inspect purchases and explain budgeting."))
