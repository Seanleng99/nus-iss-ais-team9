import pytest
from coach_i18n import catalog, translate
from coach_trace import make_event, safe_details, safe_event
from coach_trace.review import BLOCK_REASONS, CATEGORIES, reason_keys, review_metadata


def test_review_metadata_rejects_private_text_at_every_boundary():
    data = {"validation_reason": "REVIEW_UNKNOWN_SECTION", "policy_clause_refs": ["EV-03", "PRIVATE"],
            "block_reasons": ["model_review", "PRIVATE"], "review_block_categories": ["factual_qualification", "PRIVATE"],
            "request_allowed": True, "answer_complete": True, "policy_notes": ["PRIVATE"],
            "validation_message": "PRIVATE"}
    trace_id = "12345678-1234-1234-1234-123456789abc"
    event = safe_event(make_event("compliance.completed", trace_id, details=data), trace_id)
    assert event["details"] == safe_details(data)
    assert "PRIVATE" not in str(review_metadata(data)) + str(event)
    assert safe_details({"validation_reason": "PRIVATE"}) == {}


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
def test_every_review_reason_has_reviewed_localized_text(locale):
    for code in BLOCK_REASONS | CATEGORIES:
        if code == "model_review":
            continue
        key = "safety.reason." + code
        assert key in catalog(locale) and translate(key, locale) != key


def test_technical_failure_does_not_render_fallback_category_as_violation():
    assert reason_keys({"block_reasons": ["review_contract_unverified"],
                        "review_block_categories": ["unverifiable_claim"]}) == [
                            "safety.reason.review_contract_unverified"]
    assert reason_keys({"block_reasons": ["policy_evidence_missing"]}) == [
        "safety.reason.policy_evidence_missing"]
    assert reason_keys({"block_reasons": ["PRIVATE"]}) == []


@pytest.mark.parametrize("value", [None, 7, "PRIVATE", [], {"validation_reason": []}])
def test_malformed_review_metadata_does_not_crash_or_render(value):
    assert review_metadata(value) == {} and reason_keys(value) == []
