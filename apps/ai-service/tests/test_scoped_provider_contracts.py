"""Provider questions and confirmed-plan evidence stay scoped after routing."""

import json

from app.capabilities.registry import CapabilityRegistry
from app.core.config import Settings
from app.core.schemas import AgentTask, CapabilityName, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


def test_confirmed_capacity_does_not_require_raw_income_for_saved_allocation_arithmetic():
    coach = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=LocalFixtureModelGateway())
    task = AgentTask(agent="budget", sanitized_message="Calculate capacity from the confirmed allocation.",
        input_data={"saved_budget_capacity": {"source": "confirmed_plan", "period_start": "2026-10-01",
            "take_home_income": 6500, "planned_expenses": 3950, "estimated_savings_capacity": 1600,
            "unallocated_income": 950, "calculation_method": "Confirmed allocation"}},
        context_features={"has_monthly_income": True, "task_assignment": {"requires_income": False, "requires_capacity": True}})
    grounding = coach.agents["budget"]._ground(task, task.sanitized_message)
    assert grounding["savings"] == 1600 and grounding["capacity"]["period_start"] == "2026-10-01"


def test_conditional_education_provider_uses_requesting_question_and_distinct_fingerprint():
    coach = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"))
    request = CoachRequest(user_id="u", session_id="s", message="Explain liquidity for savings; separately explain diversification.")
    state = {"request": request, "sanitized_message": request.message, "selected_agents": ["budget", "investment_education"],
        "task_assignments": [{"agent": "investment_education", "question": "Explain diversification", "education_topics": ["diversification"]}]}
    provider = coach._create_task(state, "investment_education", requested_by="budget", provider_question="Explain liquidity for savings")
    provider.context_features["education_topics"] = ["liquidity"]
    assert provider.sanitized_message == "Explain liquidity for savings"
    independent = coach._create_task(state, "investment_education")
    definition = CapabilityRegistry().get(CapabilityName.EDUCATION_CONTEXT)
    assert coach._capability_input_fingerprint(state, definition, provider) != coach._capability_input_fingerprint(state, definition, independent)


def test_independent_budget_concept_stays_conceptual_while_serving_goal_capacity():
    class Gateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
                return json.dumps({"selected_agents": ["budget", "goal_strategy"], "rationale": ["Separate questions."],
                    "task_assignments": [
                        {"agent": "budget", "question": "Explain budgeting", "source_quotes": ["Explain budgeting"],
                         "requires_income": False, "requires_capacity": False, "requires_spending": False},
                        {"agent": "goal_strategy", "question": "Assess whether I can fund my goal", "source_quotes": ["Assess whether I can fund my goal"],
                         "requires_capacity": True}]})
            return super().generate(**kwargs)
    request = CoachRequest(user_id="u", session_id="s", message="Explain budgeting. Assess whether I can fund my goal.",
        snapshot={"goals": [{"name": "Laptop", "target_amount": {"amount": 3600}, "current_amount": {"amount": 600}, "target_months": 6}]},
        saved_budget_capacity={"source": "confirmed_plan", "period_start": "2026-10-01", "currency": "SGD", "take_home_income": 6500,
            "planned_expenses": 3950, "estimated_savings_capacity": 1600, "unallocated_income": 950, "calculation_method": "Confirmed allocation"})
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=Gateway()).handle(request)
    assert not response.blocked
    budget = next(result for result in response.agent_results if result.agent == "budget")
    goal = next(result for result in response.agent_results if result.agent == "goal_strategy")
    assert budget.data["calculation_status"] == "no_financial_inputs" and "savings" not in budget.data
    assert goal.data["combined_feasibility"]["monthly_capacity"] == 1600
