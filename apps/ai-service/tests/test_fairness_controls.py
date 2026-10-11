"""Enforce reviewer verdicts without making fixture-model bias-detection claims."""

import json

import pytest

from app.core.config import Settings
from app.core.prompts import FAIRNESS_POLICY, PromptCatalog
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator

STEREOTYPE = "Women are bad at managing money."


class FairnessReviewGateway(LocalFixtureModelGateway):
    def __init__(self, *, keep_blocking=False, locate=True, mixed=False):
        self.rounds = 0
        self.writes = 0
        self.keep_blocking = keep_blocking
        self.locate = locate
        self.mixed = mixed

    def generate(self, **kwargs):
        role = kwargs["system_prompt"].splitlines()[0]
        payload = json.loads(kwargs["user_prompt"])
        if role == "PROMPT_ID: agent_spending":
            self.writes += 1
            return json.dumps({
                "summary": "Recorded food spending is SGD 50. " + (
                    STEREOTYPE if self.writes == 1 or self.keep_blocking else
                    "These totals describe recorded expenses only."
                ),
                "rationale": ["The supplied record contains one food expense."], "confidence": 0.8,
            })
        if role == "PROMPT_ID: answer_correction":
            return json.dumps({"replacements": [
                {"issue_id": issue["issue_id"], "replacement": (
                    STEREOTYPE if self.keep_blocking else "These totals describe recorded expenses only."
                )} for issue in payload["issues"]
            ]})
        if role == "PROMPT_ID: risk_compliance":
            self.rounds += 1
            assert FAIRNESS_POLICY in kwargs["system_prompt"]
            if STEREOTYPE in payload["draft_answer"]:
                return json.dumps({
                    "blocked": True, "request_allowed": True, "complete": True,
                    "financial_language_safe": True, "missing_points": [],
                    "block_categories": ["demographic_assumption"] + (["privacy"] if self.mixed else []),
                    "summary": "An unsupported demographic assumption requires removal.",
                    "rationale": ["Financial records do not establish group traits."],
                    "policy_notes": ["Remove the unsupported demographic claim."], "confidence": 0.9,
                    "blocking_issues": [{
                        "section_id": "spending", "category": "demographic_assumption",
                        "action": "remove_claim", "requirement": "Remove the demographic assumption; preserve recorded totals.",
                        **({"claim_quote": STEREOTYPE} if self.locate else {}),
                    }],
                })
        return super().generate(**kwargs)


def ask(gateway, message="Analyze my October 2026 spending."):
    return AgentOrchestrator(
        config=Settings(_env_file=None, MODEL_PROVIDER="local_fixture"), gateway=gateway,
    ).handle(CoachRequest(
        user_id="fairness-synthetic", session_id="fairness-review", message=message,
        requested_agents=["spending"], snapshot={"period_start": "2026-10-01", "recent_transactions": [
            {"description": "Food", "category": "food", "amount": {"amount": 50}, "occurred_on": "2026-10-02"},
        ]},
    ))


def test_demographic_assumption_is_removed_and_independently_reviewed():
    gateway = FairnessReviewGateway()
    response = ask(gateway)
    assert not response.blocked
    assert gateway.rounds == 2
    assert STEREOTYPE not in response.model_dump_json()
    assert "50" in response.answer
    spending = next(result for result in response.agent_results if result.agent.value == "spending")
    assert spending.data["category_totals"] == {"food": 50}


@pytest.mark.parametrize("options", [
    {"keep_blocking": True}, {"locate": False}, {"mixed": True},
])
def test_unverified_or_unsafe_fairness_correction_remains_withheld(options):
    gateway = FairnessReviewGateway(**options)
    response = ask(gateway)
    assert response.blocked
    assert STEREOTYPE not in response.model_dump_json()
    assert gateway.rounds <= 3  # Structured contract retries are also bounded.


@pytest.mark.parametrize("message", [
    "I have a disability and medical expenses. Analyze my October spending.",
    "I am Malay. Analyze my October spending.",
    "The stereotype 'women are bad at money' is wrong. Analyze my October spending.",
])
def test_identity_disclosures_and_rejected_stereotypes_do_not_trigger_a_lexical_refusal(message):
    assert not ask(LocalFixtureModelGateway(), message).blocked


def test_shared_fairness_policy_changes_effective_prompt_identity(monkeypatch):
    catalog = PromptCatalog()
    before = catalog.content_hash
    for prompt_id in catalog._prompts:
        assert FAIRNESS_POLICY in catalog.get(prompt_id)
    monkeypatch.setattr("app.core.prompts.FAIRNESS_POLICY", FAIRNESS_POLICY + " Revised fairness rule.")
    assert catalog.content_hash != before
