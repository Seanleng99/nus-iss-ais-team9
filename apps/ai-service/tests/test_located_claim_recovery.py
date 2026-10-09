"""Localized corrections preserve facts and prose, then receive independent review."""

import json

import pytest
from test_conditional_financial_dependencies import RecordingGateway, request

from app.core.claim_corrections import ClaimCorrections, apply_edits, correction_edits
from app.core.config import Settings
from app.core.repair_budget import repair_time_estimate
from app.core.schemas import Transaction
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator


class ClaimGateway(RecordingGateway):
    def __init__(self, *, heading=False, invalid=False, reject_partial=False, prohibited=False, renumber=False):
        super().__init__()
        self.heading, self.invalid, self.reject_partial, self.prohibited = heading, invalid, reject_partial, prohibited
        self.reviews = 0
        self.renumber = renumber

    def generate(self, **kwargs):
        role = kwargs["system_prompt"].splitlines()[0]
        payload = json.loads(kwargs["user_prompt"])
        if role == "PROMPT_ID: agent_spending":
            self.calls.append(kwargs)
            return json.dumps({"summary": "Recorded Food is SGD 660.\n\nFood spending was unchanged.\n\nThe observation window is partial.",
                               "rationale": ["Owned ledger records."], "confidence": 0.8})
        if role == "PROMPT_ID: agent_investment_education" and self.heading:
            self.calls.append(kwargs)
            return json.dumps({"ordered_options": [{"topic": topic, "model_text": "A collective investment vehicle."}
                                                   for topic in payload["grounding"]["ordered_topics"]],
                               "rationale": ["General concepts."], "confidence": 0.8})
        if role == "PROMPT_ID: answer_correction":
            self.calls.append(kwargs)
            return json.dumps({"replacements": [{"issue_id": "review_6" if self.invalid else issue["issue_id"],
                "replacement": ("2. Conventional mutual funds" if self.renumber else "1. Conventional mutual funds")
                if self.heading else "Food spending decreased from SGD 680 to SGD 660."}
                for issue in payload["issues"]]})
        if role == "PROMPT_ID: risk_compliance":
            self.reviews += 1
            if self.reviews == 1 or self.reject_partial:
                self.calls.append(kwargs)
                quote = "1. Funds" if self.heading else "Food spending was unchanged."
                return json.dumps({"blocked": True, "request_allowed": not self.prohibited, "complete": True,
                    "missing_points": [], "financial_language_safe": True,
                    "block_categories": ["prohibited_request" if self.prohibited else "factual_qualification"],
                    "blocking_issues": [{"section_id": "education_1" if self.heading else "spending",
                        "claim_quote": quote, "action": "qualify", "requirement": "Use the exact scoped meaning."}],
                    "summary": "Qualification required.", "rationale": ["The stated meaning needs correction."],
                    "policy_notes": ["Use grounded scope."], "confidence": 1})
        return super().generate(**kwargs)


def run(gateway, heading=False, **limits):
    message = "Explain mutual funds and ETFs as two numbered options, in that order." if heading else "Analyze October 2026 spending patterns."
    role = "investment_education" if heading else "spending"
    req = request(message, [role])
    req.snapshot.historical_transactions = [Transaction(description="Food", category="food", amount={"amount": 680}, occurred_on="2026-09-02")]
    return AgentOrchestrator(config=Settings(_env_file=None, MODEL_PROVIDER="local_fixture", **limits), gateway=gateway).handle(req)


def calls(gateway, role):
    return [c for c in gateway.calls if c["system_prompt"].startswith("PROMPT_ID: " + role + "\n")]


def test_local_replacement_preserves_unaffected_text_and_financial_grounding():
    gateway = ClaimGateway()
    response = run(gateway)
    assert not response.blocked and gateway.reviews == 2
    assert len(calls(gateway, "agent_spending")) == 1
    assert len(calls(gateway, "answer_correction")) == 1
    assert response.answer == "Recorded Food is SGD 660.\n\nFood spending decreased from SGD 680 to SGD 660.\n\nThe observation window is partial."
    reviews = [json.loads(c["user_prompt"]) for c in calls(gateway, "risk_compliance")]
    assert reviews[0]["agent_results"][0]["data"] == reviews[1]["agent_results"][0]["data"]
    assert response.agent_results[0].summary == response.answer


def test_app_rendered_heading_can_be_corrected_without_regenerating_options():
    gateway = ClaimGateway(heading=True)
    response = run(gateway, heading=True)
    assert not response.blocked and gateway.reviews == 2
    assert response.answer.startswith("1. Conventional mutual funds\n\n")
    assert len(calls(gateway, "agent_investment_education")) == 1
    assert response.audit["turn_decision"]["referents"]
    reviews = [json.loads(c["user_prompt"]) for c in calls(gateway, "risk_compliance")]
    assert response.answer[len("1. Conventional mutual funds"):] == reviews[0]["draft_answer"][8:]
    assert next(s for s in reviews[1]["review_sections"] if s["section_id"] == "education_1")["end"] == len("1. Conventional mutual funds")


def test_invalid_replacement_can_only_release_a_separately_reviewed_reduced_answer():
    gateway = ClaimGateway(invalid=True)
    response = run(gateway)
    assert not response.blocked and gateway.reviews == 2
    assert len(calls(gateway, "answer_correction")) == 2
    assert "Food spending was unchanged" not in response.answer
    assert "Recorded Food is SGD 660" in response.answer
    assert response.audit["partial_answer"] and response.audit["answer_status"] == "incomplete"
    assert response.audit["turn_decision"]["referents"] == []


def test_heading_correction_cannot_renumber_options_or_retain_stale_referents():
    gateway = ClaimGateway(heading=True, renumber=True)
    response = run(gateway, heading=True)
    assert len(calls(gateway, "answer_correction")) == 2
    assert "2. Conventional mutual funds" not in response.answer
    assert response.audit["partial_answer"] and response.audit["turn_decision"]["referents"] == []


def test_reduced_answer_never_bypasses_another_blocking_or_invalid_review():
    response = run(ClaimGateway(invalid=True, reject_partial=True))
    assert response.blocked
    assert "Recorded Food" not in response.answer


def test_prohibited_request_never_reaches_local_repair_or_partial_release():
    gateway = ClaimGateway(prohibited=True)
    response = run(gateway)
    assert response.blocked and gateway.reviews == 1
    assert not calls(gateway, "answer_correction")


def test_insufficient_call_budget_skips_correction_but_can_review_a_partial_answer():
    gateway = ClaimGateway()
    response = run(gateway, MAX_MODEL_CALLS_PER_RUN=6)
    assert not calls(gateway, "answer_correction")
    assert response.audit["partial_answer"] and gateway.reviews == 2
    assert "Food spending was unchanged" not in response.answer


def test_insufficient_call_budget_for_partial_review_keeps_the_answer_withheld():
    gateway = ClaimGateway()
    response = run(gateway, MAX_MODEL_CALLS_PER_RUN=4)
    assert response.blocked and gateway.reviews == 1
    assert not calls(gateway, "answer_correction")


def test_deadline_forecast_never_releases_an_unreviewed_partial_answer(monkeypatch):
    monkeypatch.setattr("app.orchestrator.repair_time_estimate", lambda *args, **kwargs: 1000)
    gateway = ClaimGateway()
    response = run(gateway)
    assert response.blocked and gateway.reviews == 1
    assert not calls(gateway, "answer_correction")


def test_paragraph_removal_crossing_a_summary_boundary_removes_its_rejected_prose():
    from app.core.claim_corrections import corrected_results
    from app.core.schemas import AgentResult

    summary = "Bad claim.\n\nA supported observation."
    draft = "Prefix. " + summary + "\n\nAnother supported part."
    result = AgentResult(agent="spending", summary=summary, data={"category_totals": {"food": 660}})
    edits = [(0, draft.index("\n\n"), "")]
    corrected = corrected_results([result], draft, edits)[0]
    assert "Bad claim" not in corrected.summary
    assert "A supported observation" in corrected.summary
    assert corrected.data == result.data


@pytest.mark.parametrize("replacements", [
    [{"issue_id": "review_2", "replacement": "Unrelated"}],
    [{"issue_id": "review_1", "replacement": "A"}, {"issue_id": "review_1", "replacement": "B"}],
    [{"issue_id": "review_1", "replacement": ""}],
])
def test_correction_identity_and_nonempty_qualification_are_enforced(replacements):
    issues = [{"issue_id": "review_1", "claim_start": 2, "claim_end": 5, "action": "qualify"}]
    with pytest.raises(ModelGatewayError):
        correction_edits(ClaimCorrections(replacements=replacements), issues)


def test_splicing_cannot_change_other_claims_or_overlapping_ranges():
    assert apply_edits("prefix bad suffix", [(7, 10, "qualified")]) == "prefix qualified suffix"
    with pytest.raises(ModelGatewayError):
        apply_edits("prefix bad suffix", [(7, 10, "A"), (9, 11, "B")])


def test_local_repair_forecast_reserves_a_pass_without_requiring_every_optional_retry():
    observations = [{"component": "risk_compliance", "status": "completed", "duration_ms": 14000},
                    {"component": "agent_investment_education", "status": "completed", "duration_ms": 15000}]
    assert repair_time_estimate(observations, {"answer_correction", "risk_compliance"}, attempts=1) == 29
    assert repair_time_estimate(observations, {"answer_correction", "risk_compliance"}) == 58


def test_synthesis_repair_does_not_restore_a_removed_source_gap():
    from types import SimpleNamespace
    from unittest.mock import patch

    from coach_i18n import translate

    from app.core.schemas import AgentResult, CoachRequest, SynthesisDecision
    coach = AgentOrchestrator(config=Settings(_env_file=None, MODEL_PROVIDER="local_fixture"))
    req = CoachRequest(user_id="u", session_id="s", message="Explain supported diversification and identify unsupported current tax rules.")
    gap = translate("education.insufficient_evidence", "English")
    result = AgentResult(agent="investment_education", summary="Supported explanation.\n\n" + gap,
        data={"evidence_status": "partial", "unanswered_topics": ["current personal tax treatment"]})
    corrected = "Supported diversification explanation. Current personal tax rules are not established by the retrieved passages."
    state = {"request": req, "trace_id": "00000000-0000-0000-0000-000000000001", "sanitized_message": req.message,
             "agent_results": [result], "draft_answer": result.summary,
             "synthesis_feedback": ["State the specific unsupported portion without blanket insufficiency."]}
    with patch("app.orchestrator.generate_structured_response", return_value=SynthesisDecision(answer=corrected)), \
            patch.object(coach, "_event", return_value=SimpleNamespace()):
        assert coach._synthesize(state)["draft_answer"] == corrected
