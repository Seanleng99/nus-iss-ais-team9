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
