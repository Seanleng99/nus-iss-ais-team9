"""Owned evidence and operation contracts for the failed Edge acceptance flows."""

import json

import pytest
from test_budget_capture import CaptureGateway
from test_budget_records import CONTEXT, OCT
from test_conditional_semantic_education import ConditionalGateway, workflow
from test_education_semantic_coverage import RecordingRetriever, coverage

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


class RecordingGateway(LocalFixtureModelGateway):
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return super().generate(**kwargs)


@pytest.mark.parametrize("income", [None, {"amount": 5000, "currency": "USD"}])
@pytest.mark.parametrize("message,action", [
    ("Show all my saved budgets.", "read"),
    ("Compare my saved budgets for November and December 2026.", "compare"),
])
def test_record_reads_are_reviewed_with_actual_scoped_evidence(message, action, income):
    records = {f"2026-{month}-01": {"period_start": f"2026-{month}-01", "currency": "SGD",
               "categories": {"food": limit, "housing": 1500}, "planning": {"savings_target": 1000}}
               for month, limit in (("11", 600), ("12", 650))}
    gateway = RecordingGateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="synthetic", session_id="reads", message=message,
                     snapshot={"monthly_income": income},
                     budget_period_start="2026-10-01", budget_context={"today": "2026-10-05",
                     "selected_period": "2026-10-01", "budgets_by_period": records,
                     "budget_periods": list(records), "request_scope": {"operations": ["budgets"]}}))
    assert not response.blocked
    budget = next(item for item in response.agent_results if item.agent == "budget")
    assert "unsaved planning settings" not in budget.summary
    assert "600.00" in budget.summary and "650.00" in budget.summary
    review = json.loads(next(call for call in gateway.calls
                            if call["system_prompt"].startswith("PROMPT_ID: risk_compliance"))["user_prompt"])
    read = review["agent_results"][0]["data"]["budget_record_read"]
    assert read["action"] == action and read["read_only"] is True
    assert "capacity" not in budget.data
    assert [r["period_start"] for r in read["records"]] == list(records)
    assert "2026-10-01" not in [r["period_start"] for r in read["records"]]


def test_a_record_read_cannot_carry_edit_fields_even_when_the_model_claims_read_only():
    draft = {"action": "workspace", "workspace": {"operation": "budgets",
             "payload_json": json.dumps({"action": "read", "scope": {"kind": "all"},
             "categories": [{"category": "food", "limit_amount": 999}]})}}
    from app.models.gateway import ModelGatewayError
    with pytest.raises(ModelGatewayError) as raised:
        AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"),
                          gateway=CaptureGateway(draft)).handle(CoachRequest(
            user_id="synthetic", session_id="read-edits", message="Show all my saved budgets."))
    assert raised.value.code == "INVALID_STRUCTURED_RESPONSE"


def test_general_budget_definitions_do_not_calculate_profile_allocations():
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(CoachRequest(
        user_id="synthetic", session_id="definitions", requested_agents=["budget"],
        message="In general, explain planned category limits, actual recorded spending, and remaining budget. No proposed amounts are needed.",
        snapshot={"monthly_income": {"amount": 5000}}))
    assert not response.blocked
    budget = next(item for item in response.agent_results if item.agent == "budget")
    assert budget.data["calculation_status"] == "no_financial_inputs"
    assert "disposable_income" not in budget.data and "savings" not in budget.data
    assert "5,000" not in response.answer and "5000" not in response.answer


def test_mixed_read_only_calculation_remains_visible_when_education_is_unverified():
    gateway = ConditionalGateway(support=coverage(quote="This quote is absent from accepted passages."))
    response = workflow(gateway, RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic", session_id="mixed", requested_agents=["budget"],
        message="Calculate my monthly disposable income and estimated savings capacity from my profile income, and explain diversification and investment risk using approved education sources. This is a read-only calculation and educational explanation.",
        snapshot={"monthly_income": {"amount": 5000}}))
    assert not response.blocked
    assert "5,000.00" in response.answer and "1,000.00" in response.answer
    assert "unconfirmed" in response.answer and "could not be verified" in response.answer
    assert not response.sources


def test_goal_range_keeps_separate_capacities_and_missing_month_visible_on_education_gap():
    gateway = ConditionalGateway(support=coverage(quote="This quote is absent from accepted passages."))
    response = workflow(gateway, RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic", session_id="goal-range-gap", requested_agents=["goal_strategy"],
        message="Assess my goal affordability using my budgets from October through December 2026, and explain diversification using approved sources.",
        budget_context=CONTEXT, saved_budget_capacity=OCT,
        snapshot={"goals": [{"name": "Course", "target_amount": {"amount": 10800}, "target_months": 12}]}))
    assert not response.blocked
    goal = next(item for item in response.agent_results if item.agent == "goal_strategy")
    assert [row["status"] for row in goal.data["period_feasibility"]] == ["shortfall", "feasible", "unavailable"]
    assert all(amount in goal.summary for amount in ("900.00", "700.00", "1,000.00", "200.00"))
    assert "2026-12-01" in goal.summary and "unavailable" in goal.summary
    assert "could not be verified" in goal.summary and not response.sources
