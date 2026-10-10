"""Router failures retain precise static provenance codes and one correction."""
import json

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class RouterGateway(LocalFixtureModelGateway):
    def __init__(self, updates, corrected=None):
        self.updates, self.corrected, self.calls = updates, corrected, []

    def generate(self, **kwargs):
        assert kwargs["system_prompt"].startswith("PROMPT_ID: router")
        self.calls.append(kwargs)
        message = json.loads(kwargs["user_prompt"])["message"]
        data = {"selected_agents": ["goal_strategy"], "rationale": ["Read the owned goal."],
            "task_assignments": [{"agent": "goal_strategy", "question": message, "source_quotes": [message]}]}
        data.update(self.corrected if len(self.calls) > 1 and self.corrected is not None else self.updates)
        return json.dumps(data)


def route(gateway):
    request = CoachRequest(user_id="synthetic-router-contract", session_id="synthetic-router-contract",
        message="Show my saved Education fund goal.", requested_agents=["goal_strategy"])
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway)._route({
        "request": request, "sanitized_message": request.message,
        "trace_id": "synthetic-router-contract", "executed_at": "2026-10-11"})


@pytest.mark.parametrize("updates,reason", [
    ({"reference_scope": "current_message"}, "ROUTER_REFERENCE_QUOTE_INVALID"),
    ({"reference_scope": "current_message", "reference_quote": "saved Education fund goal",
      "reference_subject_quote": "Education fund"}, "ROUTER_REFERENCE_SPANS_INVALID"),
    ({"selected_agents": ["budget"]}, "ROUTER_SELECTION_MISMATCH"),
    ({"task_assignments": [{"agent": "goal_strategy", "question": "Show the goal.",
      "source_quotes": ["Private fabricated quote"]}]}, "ROUTER_ASSIGNMENT_PROVENANCE_INVALID"),
    ({"education_topics": ["made-up-topic"]}, "ROUTER_TOPIC_INVALID"),
    ({"education_search_terms": ["my income 5432"]}, "ROUTER_SEARCH_TERMS_INVALID"),
    ({"task_assignments": [{"agent": "goal_strategy", "question": "Show the goal.",
      "source_quotes": ["Education fund"], "education_topics": ["made-up-topic"]}]}, "ROUTER_TASK_TOPIC_INVALID"),
    ({"task_assignments": [{"agent": "goal_strategy", "question": "Show the goal.",
      "source_quotes": ["Education fund"], "goal_mode": "emergency_reserve"}]}, "ROUTER_EMERGENCY_TOPIC_REQUIRED"),
])
def test_semantic_rejection_has_static_reason_and_no_generated_content(updates, reason):
    gateway = RouterGateway(updates)
    with pytest.raises(ModelGatewayError) as captured:
        route(gateway)
    assert captured.value.validation_reason == reason
    assert len(gateway.calls) == 2
    assert "Private" not in str(captured.value) and "5432" not in str(captured.value)


def test_named_subject_correction_preserves_selected_task_without_relaxing_provenance():
    gateway = RouterGateway({"reference_scope": "current_message", "reference_quote": "saved Education fund goal",
        "reference_subject_quote": "Education fund"}, corrected={"reference_scope": "none"})
    state = route(gateway)
    assert len(gateway.calls) == 2
    assert state["selected_agents"] == ["goal_strategy"]
    assert "distinct, unique, nonoverlapping" in gateway.calls[0]["system_prompt"]
    assert "distinct, unique current-message spans" in gateway.calls[1]["system_prompt"]
