"""Only unchanged financial authority and a second independent verdict permit release."""

import json

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class FinancialReviewGateway(LocalFixtureModelGateway):
    def __init__(self, category="factual_qualification", keep_blocking=False):
        self.rounds = 0
        self.writes = []
        self.category = category
        self.keep_blocking = keep_blocking

    def generate(self, **kwargs):
        role = kwargs["system_prompt"].splitlines()[0]
        payload = json.loads(kwargs["user_prompt"])
        if role == "PROMPT_ID: agent_spending":
            self.writes.append(payload)
            return json.dumps({"summary": ("Your entire household spent SGD 50 on food."
                if len(self.writes) == 1 else "Recorded food spending is SGD 50; household coverage is incomplete."),
                "rationale": ["The supplied records contain one food expense."], "confidence": 0.8})
        if role == "PROMPT_ID: risk_compliance":
            self.rounds += 1
            if self.rounds == 1 or self.keep_blocking:
                return json.dumps({"blocked": True, "request_allowed": True, "complete": True,
                    "missing_points": [], "financial_language_safe": True,
                    "blocking_issues": [{"section_id": "spending", "requirement": "State that recorded coverage is incomplete."}],
                    "block_categories": [self.category], "policy_notes": ["Coverage needs qualification."],
                    "summary": "Correction required.", "rationale": ["Recorded totals are not complete household spending."], "confidence": 1})
        return super().generate(**kwargs)


def ask(gateway):
    coach = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway)
    req = CoachRequest(user_id="u", session_id="s", message="Analyze October 2026 spending patterns.",
        snapshot={"period_start": "2026-10-01", "recent_transactions": [
            {"description": "Food", "category": "food", "amount": {"amount": 50}, "occurred_on": "2026-10-02"}]})
    return coach.handle(req)


def test_qualification_correction_reuses_same_financial_grounding_and_is_reviewed():
    gateway = FinancialReviewGateway()
    response = ask(gateway)
    assert not response.blocked and gateway.rounds == 2
    assert len(gateway.writes) == 2
    assert gateway.writes[0]["grounding"] == gateway.writes[1]["grounding"]
    assert gateway.writes[1]["missing_points"] == ["State that recorded coverage is incomplete."]
    assert "household coverage is incomplete" in response.answer
    assert "_financial_grounding_snapshot" not in response.model_dump_json()


@pytest.mark.parametrize("category", ["unverifiable_claim", "personal_advice"])
def test_nonrepairable_verdict_never_rewrites_or_releases(category):
    gateway = FinancialReviewGateway(category)
    response = ask(gateway)
    assert response.blocked and gateway.rounds == 1 and len(gateway.writes) == 1


def test_rejected_correction_remains_withheld_without_a_third_attempt():
    gateway = FinancialReviewGateway(keep_blocking=True)
    response = ask(gateway)
    assert response.blocked and gateway.rounds == 2 and len(gateway.writes) == 2


def test_changed_authority_cannot_be_used_for_financial_correction():
    from app.core.financial_grounding import FinancialGroundingSnapshot
    from app.core.schemas import AgentTask
    task = AgentTask(agent="budget", sanitized_message="Explain the saved allocation.")
    snapshot = FinancialGroundingSnapshot.capture(task, {"savings": 1600})
    with pytest.raises(ModelGatewayError, match="authority changed"):
        snapshot.for_repair(task, {"savings": 1700})


def test_private_diagnostic_redacts_identifiers_and_is_not_returned(tmp_path):
    from app.core.review_diagnostics import save_review_diagnostic
    from app.core.schemas import ComplianceDecision
    from app.core.run_trace import workflow_id
    token = workflow_id.set("12345678-1234-1234-1234-123456789abc")
    try:
        save_review_diagnostic(str(tmp_path), "Contact +65 9123 4567. Recorded food is SGD 50.", [],
            ComplianceDecision(blocked=True, summary="Qualification missing", rationale=["Coverage is incomplete"],
                               policy_notes=["Coverage is incomplete"], block_categories=["factual_qualification"], confidence=1), [])
    finally:
        workflow_id.reset(token)
    files = list(tmp_path.glob("review-*.json"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "9123 4567" not in content and "Recorded food is SGD 50" in content
