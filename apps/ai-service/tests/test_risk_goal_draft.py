"""Risk can inspect unsaved Goal proposals without treating them as authority."""

import json

import pytest

from app.agents.goal_capture import GoalDraft
from app.agents.risk_compliance import RiskComplianceAgent
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentResult, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.rag.policy import LocalPolicyRetriever


class DraftReviewGateway(LocalFixtureModelGateway):
    def __init__(self, veto):
        self.veto = veto
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps({
            "blocked": self.veto,
            "summary": "The proposal is unsaved and requires backend validation.",
            "rationale": ["The proposed fields are not proof that an operation succeeded."],
            "policy_notes": ["The answer claims a change has completed."] if self.veto else [],
            "block_categories": ["factual_qualification"] if self.veto else [],
            "confidence": 1,
        })


@pytest.mark.parametrize("action", ["create", "update", "delete"])
@pytest.mark.parametrize("veto", [False, True])
def test_goal_proposal_reaches_risk_and_preserves_its_veto(action, veto):
    draft = GoalDraft(action=action, goal_name="Holiday" if action != "create" else None,
        name="Holiday" if action == "create" else None, currency="SGD",
        target_amount=1200 if action != "delete" else None,
        current_amount=0 if action == "create" else None,
        target_months=None, questions=["What duration in months?"] if action != "delete" else [])
    request = CoachRequest(user_id="PRIVATE-USER", session_id="PRIVATE-SESSION",
        message=f"{action.title()} my Holiday goal.")
    gateway = DraftReviewGateway(veto)
    reviewer = RiskComplianceAgent(gateway, PromptCatalog(), 0.1, 800, LocalPolicyRetriever())
    summary = "The goal was saved." if veto else "An unsaved goal change was proposed."
    proposal = AgentResult(agent="goal_strategy", summary=summary, rationale=[], confidence=1,
        data={"goal_draft": draft.model_dump(mode="json"), "private_note": "PRIVATE-NOTE"})
    assert proposal._financial_grounding_snapshot is None

    decision = reviewer.validate(request, [proposal], summary)

    assert len(gateway.calls) == 1
    payload = json.loads(gateway.calls[0]["user_prompt"])
    assert payload["agent_results"][0]["data"]["goal_draft"] == draft.model_dump(mode="json")
    assert payload["evidence_refs"] == []
    assert "untrusted, unsaved proposal" in gateway.calls[0]["system_prompt"]
    assert all(value not in gateway.calls[0]["user_prompt"]
               for value in ("PRIVATE-USER", "PRIVATE-SESSION", "PRIVATE-NOTE"))
    assert decision.blocked is veto
