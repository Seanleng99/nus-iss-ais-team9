"""Projection currency survives the tool and a bounded narrative correction."""
import json

import pytest

from app.agents.goal_strategy import GoalStrategyAgent
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentNarrative, UserFinancialSnapshot
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.models.structured import generate_structured_response
from app.tools.registry import project_goals


def grounding():
    return {"calculation_scope": "saved_goal_arithmetic", "projections": [
        {"name": "Holiday", "currency": "SGD", "remaining": 1200, "target_months": 12,
         "monthly_required": 100}]}


@pytest.mark.parametrize("currency", ["SGD", "USD"])
def test_projection_preserves_owned_currency(currency):
    projections = project_goals(UserFinancialSnapshot(goals=[{"name": "Holiday",
        "target_amount": {"currency": currency, "amount": 1200},
        "current_amount": {"currency": currency, "amount": 0}, "target_months": 12}]))
    assert projections[0]["currency"] == currency and projections[0]["monthly_required"] == 100


@pytest.mark.parametrize("summary", ["Save $100 per month.", "Save 100.00 per month.",
                                    "Save USD 100 per month.", "Save USD100 per month."])
def test_ambiguous_or_wrong_currency_cannot_pass_saved_goal_narrative(summary):
    agent = GoalStrategyAgent(LocalFixtureModelGateway(), PromptCatalog(), 0.1, 800)
    with pytest.raises(ModelGatewayError, match="currency"):
        agent._validate_narrative(AgentNarrative(summary=summary, rationale=["Saved goal arithmetic."], confidence=1), grounding())


@pytest.mark.parametrize("summary", ["Save SGD 100 per month.", "Save SGD100 per month.",
                                    "Save 100 SGD per month.", "Your progress is 100%.", "Your progress is 100 %."])
def test_explicit_currency_and_percentage_only_status_remain_valid(summary):
    agent = GoalStrategyAgent(LocalFixtureModelGateway(), PromptCatalog(), 0.1, 800)
    narrative = AgentNarrative(summary=summary, rationale=["Saved goal arithmetic."], confidence=1)
    assert agent._validate_narrative(narrative, grounding()) is narrative


@pytest.mark.parametrize("currency", ["SGD", "USD", "EUR"])
@pytest.mark.parametrize("monthly_required", [77.35, 235.57])
def test_currency_rule_uses_the_current_projection_instead_of_a_benchmark_amount(currency, monthly_required):
    agent = GoalStrategyAgent(LocalFixtureModelGateway(), PromptCatalog(), 0.1, 800)
    facts = {"calculation_scope": "saved_goal_arithmetic", "projections": [
        {"currency": currency, "monthly_required": monthly_required, "remaining": monthly_required * 10}]}
    narrative = AgentNarrative(summary=f"Save {currency} {monthly_required:.2f} per month.",
        rationale=["Saved goal arithmetic."], confidence=1)
    assert agent._validate_narrative(narrative, facts) is narrative
    with pytest.raises(ModelGatewayError, match="currency"):
        agent._validate_narrative(narrative.model_copy(update={
            "summary": f"Save {monthly_required:.2f} per month."}), facts)


def test_currency_rejection_gets_one_specific_correction_with_unchanged_grounding():
    class Gateway:
        def __init__(self):
            self.calls = []
        def generate(self, **kwargs):
            self.calls.append(kwargs)
            return json.dumps({"summary": "Save $100 per month." if len(self.calls) == 1
                               else "Save SGD 100 per month.", "rationale": ["Saved goal arithmetic."], "confidence": 1})

    gateway = Gateway()
    agent = GoalStrategyAgent(gateway, PromptCatalog(), 0.1, 800)
    facts = grounding()
    result = generate_structured_response(gateway, response_type=AgentNarrative,
        system_prompt="PROMPT_ID: agent_goal_strategy", user_prompt=json.dumps({"grounding": facts}),
        temperature=0.1, max_tokens=800, validate_response=lambda response: agent._validate_narrative(response, facts))
    assert result.summary == "Save SGD 100 per month." and len(gateway.calls) == 2
    repair = json.loads(gateway.calls[1]["user_prompt"])
    assert repair["grounding"] == facts
    assert "currency" in repair["correction_feedback"]["validation_issues"]
