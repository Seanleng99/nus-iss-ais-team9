"""Independent Risk review receives the writer's scoped deterministic aggregates."""

import json

import pytest

from app.agents.risk_compliance import RiskComplianceAgent
from app.agents.spending import SpendingAgent
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentResult, AgentTask, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.rag.policy import LocalPolicyRetriever


class CoverageReviewGateway(LocalFixtureModelGateway):
    def __init__(self, *, veto):
        self.veto = veto
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps({
            "blocked": self.veto,
            "summary": (
                "The evidence does not prove habitual overspending."
                if self.veto else "The draft accurately qualifies the limited records."
            ),
            "rationale": ["Recorded totals cannot establish an enduring habit."],
            "policy_notes": ["The draft overstates limited spending evidence."] if self.veto else [],
            "block_categories": ["factual_qualification"] if self.veto else [],
            "confidence": 0.98,
        })


@pytest.mark.parametrize("veto", [False, True])
def test_dated_spending_coverage_reaches_independent_review_without_overriding_veto(veto):
    records = [{
        "description": "PRIVATE-RAW-RECEIPT",
        "category": "dining",
        "amount": {"currency": "SGD", "amount": 10},
        "occurred_on": f"2026-{month:02d}-01",
    } for month in range(1, 7)]
    request = CoachRequest(
        user_id="PRIVATE-USER-ID", session_id="PRIVATE-SESSION-ID",
        message="Do these few records prove that I habitually overspend on weekends?",
        snapshot={
            "period_start": "2026-06-01",
            "recent_transactions": records[-1:],
            "historical_transactions": [*records[:-1], {
                **records[0], "amount": {"currency": "USD", "amount": 999},
            }],
            "transaction_context": {"records_complete": False, "history_end": "2026-05-31"},
        },
    )
    prompts = PromptCatalog("v6")
    task = AgentTask(
        agent="spending", sanitized_message=request.message,
        input_data=request.snapshot.model_dump(mode="json", include={
            "period_start", "recent_transactions", "historical_transactions", "transaction_context",
        }),
    )
    writer = SpendingAgent(LocalFixtureModelGateway(), prompts, 0.2, 800)
    grounding = writer._ground(task, task.sanitized_message)
    draft = (
        "These records prove habitual weekend overspending."
        if veto else
        "The six dated records include two weekend entries totaling SGD 20 and four "
        "weekday entries totaling SGD 40. June has one SGD 10 entry. This incomplete "
        "sample does not prove a habit or overspending; the USD entry is excluded."
    )
    gateway = CoverageReviewGateway(veto=veto)
    reviewer = RiskComplianceAgent(
        gateway=gateway, prompts=prompts, temperature=0.1, max_tokens=800,
        policy_retriever=LocalPolicyRetriever(),
    )

    result = reviewer.validate(request, [AgentResult(
        agent="spending", summary=draft, rationale=[], confidence=0.8,
        data={**grounding, "unrelated_private_note": "PRIVATE-UNRELATED-NOTE"},
    )], draft)

    assert len(gateway.calls) == 1
    payload = json.loads(gateway.calls[0]["user_prompt"])
    evidence = payload["agent_results"][0]["data"]
    assert evidence["analysis_coverage"] == {
        "record_count": 6, "dated_record_count": 6, "distinct_recorded_days": 6,
        "first_recorded_on": "2026-01-01", "last_recorded_on": "2026-06-01",
        "total_amount": 60,
        "weekday": {"record_count": 4, "total_amount": 40},
        "weekend": {"record_count": 2, "total_amount": 20},
    }
    assert evidence["selected_month_coverage"]["record_count"] == 1
    assert evidence["selected_month_coverage"]["total_amount"] == 10
    assert evidence["analysis_period_start"] == "2026-06-01"
    assert evidence["analysis_period_end"] == "2026-06-30"
    assert evidence["temporal_pattern_scope"] == "selected_month"
    assert evidence["currency"] == "SGD" and evidence["excluded_currencies"] == ["USD"]
    assert evidence["transaction_context"]["records_complete"] is False
    assert evidence["data_quality"] == "limited"
    assert evidence["temporal_patterns"] == []
    for private_value in (
        "PRIVATE-RAW-RECEIPT", "PRIVATE-USER-ID", "PRIVATE-SESSION-ID", "PRIVATE-UNRELATED-NOTE",
    ):
        assert private_value not in gateway.calls[0]["user_prompt"]
    assert result.blocked is veto
