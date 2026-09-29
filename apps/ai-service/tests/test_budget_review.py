from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.orchestrator import AgentOrchestrator


def test_budget_review_routes_without_income_and_does_not_invent_amounts():
    result = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="u",
            session_id="s",
            message="Review my budget for September 2026",
            requested_agents=["budget"],
        )
    )
    budget = next(item for item in result.agent_results if item.agent.value == "budget")
    draft = budget.data["budget_draft"]
    assert draft["action"] == "review"
    assert draft["period_start"] == "2026-09-01"
    assert not draft["categories"]
    assert "planning_analysis" not in budget.data
    assert not result.blocked


def test_missing_review_period_stays_missing():
    result = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="u",
            session_id="s",
            message="Review my budget",
            requested_agents=["budget"],
        )
    )
    budget = next(item for item in result.agent_results if item.agent.value == "budget")
    assert budget.data["budget_draft"]["period_start"] is None


def test_review_followup_keeps_review_intent():
    result = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="u",
            session_id="s",
            message="September 2026",
            pending_budget={"action": "review", "period_start": None},
        )
    )
    budget = next(item for item in result.agent_results if item.agent.value == "budget")
    assert budget.data["budget_draft"]["action"] == "review"
    assert budget.data["budget_draft"]["period_start"] == "2026-09-01"
