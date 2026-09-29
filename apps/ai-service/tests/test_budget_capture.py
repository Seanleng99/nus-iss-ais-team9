import json

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


class CaptureGateway(LocalFixtureModelGateway):
    def __init__(self, draft):
        self.draft = draft
        self.capture_payload = None

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
