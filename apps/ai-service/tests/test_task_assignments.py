"""Exercise production task contracts with model choices, not fixture recognizers."""

import json

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class AssignedGateway(LocalFixtureModelGateway):
    def __init__(self, assignments, *, uses_spending=False):
        self.assignments = assignments
        self.uses_spending = uses_spending
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            return json.dumps({"selected_agents": ["spending", "budget"],
                               "rationale": ["Two distinct requested tasks."],
                               "task_assignments": self.assignments})
        # Script a separate semantic dependency decision. Router hints do not
        # veto approved options; independence is preserved by the planner.
        if kwargs["system_prompt"].startswith("PROMPT_ID: dependency_planner"):
            payload = json.loads(kwargs["user_prompt"])
            requests = [{k: v for k, v in item.items() if k != "selection_guidance"}
                        for item in payload["allowed_requests"]
                        if item["capability"] != "transaction_category_totals" or self.uses_spending]
            return json.dumps({"status": "needs_dependency" if requests else "ready", "requests": requests})
        return super().generate(**kwargs)


def test_independent_model_tasks_decline_spending_for_budgets_own_scope():
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
    plans = [json.loads(call["user_prompt"]) for call in gateway.calls
             if call["system_prompt"].startswith("PROMPT_ID: dependency_planner")]
    assert plans and plans[0]["message"] == "Teach me a budgeting method"
    assert plans[0]["allowed_requests"][0]["capability"] == "transaction_category_totals"
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


@pytest.mark.parametrize("consume_spending", [True, False])
def test_model_assignment_preserves_explicit_dataflow_and_conditional_independence(consume_spending):
    from test_conditional_financial_dependencies import request
    message = ("Reconcile recorded category totals against saved budget limits, then assess all my saved goals together."
               if consume_spending else "Describe recorded category totals separately; assess all my saved goals using saved budget capacity.")
    assignments = [
        {"agent": "spending", "question": "Describe recorded category totals.", "source_quotes": [message]},
        {"agent": "budget", "question": "Reconcile recorded totals with saved budget limits." if consume_spending else "Use saved budget capacity.",
         "source_quotes": [message], "requires_spending": consume_spending, "requires_capacity": True, "requires_income": False},
        {"agent": "goal_strategy", "question": "Assess all saved goals together using the budget capacity.",
         "source_quotes": [message], "requires_capacity": True},
    ]
    class DataflowGateway(AssignedGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
                self.calls.append(kwargs)
                return json.dumps({"selected_agents": ["spending", "budget", "goal_strategy"],
                    "rationale": ["Use the requested data flow."], "task_assignments": assignments})
            return super().generate(**kwargs)
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"),
                                 gateway=DataflowGateway(assignments, uses_spending=consume_spending)).handle(
        request(message, ["spending", "budget", "goal_strategy"], capacity=True))
    assert not response.blocked
    capabilities = {edge["capability"] for edge in response.audit["dependency_edges"]}
    assert "monthly_savings_capacity" in capabilities
    assert ("transaction_category_totals" in capabilities) is consume_spending
    routing = next(event for event in response.audit["events"] if event["event_type"] == "routing.completed")
    budget = next(item for item in routing["details"]["task_assignments"] if item["agent"] == "budget")
    assert budget["requires_spending"] is consume_spending
    assert "question" not in budget and "source_quotes" not in budget
