from datetime import UTC, datetime
from uuid import uuid4

import pytest
from coach_trace import make_event, safe_details, safe_event


def test_metadata_survives_all_contract_boundaries_without_private_content():
    trace_id = str(uuid4())
    metadata = {
        "review_block_categories": ["unverifiable_claim"],
        "question_count": 2,
        "query_topics": ["emergency fund readiness", "private unknown topic"],
        "before": {
            "selected_agents": ["budget"],
            "budget_capture": True,
            "rationale": "PRIVATE",
            "amount": 5000,
        },
        "after": {"selected_agents": ["investment_education"], "budget_capture": False},
        "prompt": "PRIVATE",
        "quote": "PRIVATE",
        "reason_code": "FOLLOW_UP_READ_ONLY",
    }
    producer = make_event("routing.override_applied", trace_id, details=metadata)
    backend = safe_event(producer, trace_id)
    viewer = safe_details(backend["details"])
    assert viewer == producer["details"] == backend["details"]
    assert viewer["question_count"] == 2
    assert viewer["review_block_categories"] == ["unverifiable_claim"]
    assert viewer["query_topics"] == ["emergency_fund_readiness"]
    assert "PRIVATE" not in str(backend)
    assert backend["schema_version"] == 1


@pytest.mark.parametrize("value", [True, -1, float("inf"), float("nan"), "2"])
def test_counts_reject_wrong_types_and_invalid_numbers(value):
    assert safe_details({"question_count": value}) == {}


def test_versions_and_legacy_frames():
    trace_id = str(uuid4())
    legacy = {
        "event_id": str(uuid4()),
        "trace_id": trace_id,
        "event_type": "task.started",
        "timestamp": datetime.now(UTC).isoformat(),
        "details": {},
    }
    assert safe_event(legacy, trace_id)["schema_version"] == 1
    with pytest.raises(ValueError, match="Unsupported"):
        safe_event({**legacy, "schema_version": 999}, trace_id)
    with pytest.raises(ValueError, match="Invalid trace"):
        safe_event(legacy, str(uuid4()))
