import json

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


class CaptureGateway(LocalFixtureModelGateway):
    def __init__(self, draft):
        self.draft = draft
        self.capture_payload = None
        self.capture_prompt = None

    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            return json.dumps(
                {
                    "selected_agents": ["budget"],
                    "rationale": ["User is setting limits."],
                    "budget_capture": True,
                }
            )
        if kwargs["system_prompt"].startswith("PROMPT_ID: budget_capture"):
            self.capture_payload = json.loads(kwargs["user_prompt"])
            self.capture_prompt = kwargs["system_prompt"]
            return json.dumps(self.draft)
        return super().generate(**kwargs)


def test_capture_all_categories_without_requiring_income():
    draft = {
        "period_start": "2026-10-01",
        "currency": "SGD",
        "categories": [
            {"category": "food", "limit_amount": 500},
            {"category": "pet care", "limit_amount": 100},
        ],
    }
    gateway = CaptureGateway(draft)
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway
    ).handle(
        CoachRequest(
            user_id="u1",
            session_id="s1",
            message="Set October 2026 budgets: food SGD 500 and pet care SGD 100",
        )
    )
    result = next(item for item in response.agent_results if item.agent.value == "budget")
    assert not response.blocked
    assert [{"category": item["category"], "limit_amount": item["limit_amount"]}
            for item in result.data["budget_draft"]["categories"]] == draft["categories"]
    assert all(item["source"] == "user" for item in result.data["budget_draft"]["categories"])
    assert "unsaved" in result.summary


def test_pending_details_reach_budget_agent_and_missing_fields_stay_null():
    draft = {
        "period_start": None,
        "currency": None,
        "categories": [{"category": "pets", "limit_amount": 100}],
    }
    gateway = CaptureGateway(draft)
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway
    ).handle(
        CoachRequest(user_id="u1", session_id="s1", message="100 for pets", pending_budget=draft)
    )
    result = next(item for item in response.agent_results if item.agent.value == "budget")
    assert result.data["budget_draft"]["period_start"] is None
    assert result.data["budget_draft"]["currency"] is None
    assert gateway.capture_payload["pending_draft"] == draft


def test_offline_fixture_budget_capture():
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(
            user_id="u1",
            session_id="s1",
            message="Set budget for October 2026 in SGD; food: 500, pet care: 100",
        )
    )
    result = next(item for item in response.agent_results if item.agent.value == "budget")
    assert result.data["budget_draft"]["period_start"] == "2026-10-01"
    assert len(result.data["budget_draft"]["categories"]) == 2


def test_workspace_draft_receives_owned_context_without_income_or_execution():
    draft = {"action": "workspace", "workspace": {"operation": "commitments",
        "payload_json": '{"period_start":"2026-10-01","protected_categories":["housing"]}'}}
    gateway = CaptureGateway(draft)
    owned = {"workspace": {"settings": {}, "goals": [{"id": "owned-goal", "name": "Reserve"}]}}
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u1", session_id="s1", message="Protect housing in my October 2026 commitments", budget_context=owned))
    result = next(r for r in response.agent_results if r.agent.value == "budget")
    assert not response.blocked
    assert result.data["budget_draft"]["workspace"] == draft["workspace"]
    assert gateway.capture_payload["recorded_context"] == owned
    assert "unsaved" in result.summary.lower()
    assert "planning_analysis" not in result.data


def test_pending_workspace_correction_retains_command_context():
    draft = {"action": "workspace", "workspace": {"operation": "cashflow", "payload_json": '{"opening_balance":2500}'}}
    gateway = CaptureGateway(draft)
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u1", session_id="s1", message="Actually use SGD 2500", pending_budget=draft))
    assert not response.blocked
    assert gateway.capture_payload["pending_draft"] == draft
    result = next(r for r in response.agent_results if r.agent.value == "budget")
    assert result.data["budget_draft"]["action"] == "workspace"


def test_simple_comparison_uses_confirmed_plan_and_a_small_contract():
    draft = {"action": "compare", "period_start": "2026-10-01", "scenarios": [{"name": "Proposed change", "savings_target": 1100}]}
    gateway = CaptureGateway(draft)
    owned = {"request_scope": {"operations": []}, "selected_period": "2026-10-01", "selected_budget": {
        "period_start": "2026-10-01", "currency": "SGD", "categories": {"housing": 1500, "food": 500},
        "planning": {"take_home_income": 3000, "income_basis": "take_home", "savings_target": 800, "expenses_confirmed": True},
    }}
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u1", session_id="s1", message="What if I save SGD 1100 in my October 2026 budget?", budget_context=owned))
    result = next(r for r in response.agent_results if r.agent.value == "budget")
    assert not response.blocked
    assert "refund_reopens" not in gateway.capture_prompt
    assert "payload_json" not in gateway.capture_prompt
    assert result.data["planning_analysis"]["expense_total"] == 2000
    assert result.data["planning_analysis"]["comparisons"][0]["funding_gap"] == 100
    assert result.data["budget_draft"]["planning"]["expenses_confirmed"] is False


def test_explicit_different_month_does_not_borrow_selected_income():
    draft = {"action": "compare", "period_start": "2026-11-01", "currency": "SGD", "scenarios": [{"name": "Proposed change", "savings_target": 1100}]}
    gateway = CaptureGateway(draft)
    owned = {"request_scope": {"operations": []}, "selected_period": "2026-10-01", "selected_budget": {
        "period_start": "2026-10-01", "currency": "SGD", "categories": {"housing": 1500},
        "planning": {"take_home_income": 3000, "savings_target": 800, "income_basis": "take_home"},
    }}
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u1", session_id="s1", message="What if I save SGD 1100 in my November 2026 budget?", budget_context=owned))
    result = next(r for r in response.agent_results if r.agent.value == "budget")
    assert result.data["planning_analysis"]["unallocated"] is None
    assert result.data["planning_analysis"]["comparisons"] == []
