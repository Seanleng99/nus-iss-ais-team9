from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.orchestrator import AgentOrchestrator


def run(message, **kwargs):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(user_id="u1", session_id="s1", message=message, **kwargs)
    )


def test_create_goal_without_income_routes_and_extracts():
    reply = run(
        "Create goal; name: Emergency fund; currency: SGD; target_amount: 12000; current_amount: 1000; target_months: 12"
    )
    assert not reply.blocked
    result = next(r for r in reply.agent_results if r.agent == "goal_strategy")
    assert result.data["goal_draft"]["target_amount"] == 12000
    assert "unsaved" in result.summary


def test_pending_followup_and_delete():
    reply = run("current_amount: 0", pending_goal={"action": "create", "name": "Travel"})
    result = next(r for r in reply.agent_results if r.agent == "goal_strategy")
    assert result.data["goal_draft"]["name"] == "Travel"
    assert result.data["goal_draft"]["current_amount"] == 0
    assert result.data["goal_draft"]["currency"] is None
    reply = run("Delete goal; goal_name: Travel")
    result = next(r for r in reply.agent_results if r.agent == "goal_strategy")
    assert result.data["goal_draft"]["action"] == "delete"


def test_budget_creation_with_goal_analysis_is_not_goal_mutation():
    from app.agents.goal_capture import goal_change_request
    assert not goal_change_request("Create a budget, assess my savings goal, and summarize spending.")
    assert not goal_change_request("Create my monthly budget and help plan a savings goal.")
    assert goal_change_request("Update my Emergency fund goal target to SGD 15000")
