from datetime import UTC, datetime
from uuid import uuid4

from app.infrastructure.run_trace import safe_event


def test_compliance_block_reasons_are_persisted_as_safe_codes():
    trace_id = str(uuid4())
    saved = safe_event(
        {
            "event_id": str(uuid4()),
            "trace_id": trace_id,
            "event_type": "compliance.completed",
            "timestamp": datetime.now(UTC).isoformat(),
            "details": {
                "blocked": True,
                "policy_note_count": 0,
                "block_reasons": ["model_review", "The reviewer said: buy this ETF now!"],
            },
        },
        trace_id,
    )
    # Fixed category codes survive; free-form model wording never does.
    assert saved["details"]["block_reasons"] == ["model_review"]
    assert saved["details"]["blocked"] is True
    assert saved["details"]["policy_note_count"] == 0


def test_blocked_result_sanitization_preserves_only_safe_compliance_metadata():
    from app.domain.schemas import sanitize_blocked_agent_results
    results = sanitize_blocked_agent_results([
        {"agent": "risk_compliance", "summary": "Private rejected reviewer prose", "data": {
            "block_reasons": ["model_review", "rejected prose"],
            "review_block_categories": ["factual_qualification"], "policy_clause_refs": ["EV-03", "invented"],
            "request_allowed": True, "answer_complete": True,
            "validation_reason": "CORRECTION_OUTSIDE_RANGE", "policy_contexts": [{"text": "private"}],
            "personal_balance": 9999}},
        {"agent": "spending", "data": {"category_totals": {"food": 660}, "request_allowed": True}},
    ])
    assert results[0]["data"] == {"block_reasons": ["model_review"],
        "review_block_categories": ["factual_qualification"], "policy_clause_refs": ["EV-03"],
        "request_allowed": True, "answer_complete": True, "validation_reason": "CORRECTION_OUTSIDE_RANGE"}
    assert results[1]["data"] == {}
    assert "private" not in str(results).lower() and "9999" not in str(results)
