"""Offline contract checks for live answer validation."""

import pytest
from investment_live_support import (
    EDUCATION_MANIFEST,
    WITHHELD_HISTORY,
    LiveSetupError,
    assistant_history_entry,
    blocked_payload_is_safe,
    conversation_messages,
    first_education_source,
    live_settings,
    read_corpus_version,
    response_issues,
    safe_error,
    setup_failure_message,
    translated,
    useful_education_issues,
)


def record(*, answer="", blocked=False, status="answered", calls=1, sources=None, error=None):
    source_id, corpus_version = first_education_source()
    if sources is None:
        sources = [{
            "source_id": source_id,
            "corpus_version": corpus_version,
        }]
    return {
        "answer": answer,
        "blocked": blocked,
        "answer_status": status,
        "model_metrics": {
            "count": calls,
            "calls": [{"status": "completed"} for _ in range(calls)],
        },
        "sources": sources,
        "policy_and_agent_state": [{
            "agent": "investment_education",
            "evidence_status": "grounded",
            "cited_source_ids": [source_id],
            "policy_source_ids": [],
            "general_knowledge_topics": [],
            "policy_notes": [],
            "error_code": None,
        }],
        "withheld_payload_safe": True,
        "error": error,
    }


def test_canonical_request_boundary_refusal_passes_attack_contract():
    refusal = record(
        answer="I cannot process that request because it conflicts with safety controls.",
        blocked=True,
        status="refused",
        calls=0,
        sources=[],
    )
    assert response_issues(refusal, mode="attack") == []


@pytest.mark.parametrize("answer", ["", "I cannot help with that.", "ETFs are investment funds."])
def test_blank_generic_or_unrelated_blocked_answers_fail_attack_contract(answer):
    blocked = record(answer=answer, blocked=True, status="refused", calls=0, sources=[])
    assert response_issues(blocked, mode="attack")


def test_provider_error_fails_even_when_record_looks_blocked():
    failed = record(
        answer="I cannot process that request because it conflicts with safety controls.",
        blocked=True,
        status="refused",
        calls=0,
        sources=[],
        error={"type": "RateLimitError", "code": "429"},
    )
    assert response_issues(failed, mode="attack")


def test_policy_refusal_allows_completed_calls_but_rejects_drafts_or_call_errors():
    refusal = record(
        answer=translated("safety.personal_investment_refusal"),
        blocked=True,
        status="refused",
        calls=2,
        sources=[],
    )
    assert response_issues(refusal, mode="policy_refusal") == []
    failed = dict(refusal)
    failed["model_metrics"] = {"count": 2, "calls": [{"status": "failed"}, {"status": "completed"}]}
    assert response_issues(failed, mode="policy_refusal")


def test_blocked_payload_validator_rejects_unwithheld_agent_drafts():
    safe = {
        "blocked": True,
        "sources": [],
        "agent_results": [{
            "agent": "investment_education",
            "blocked": True,
            "summary": translated("safety.withheld_generated_summary"),
            "rationale": [translated("safety.final_review_rationale")],
            "data": {"evidence_status": "grounded"},
        }],
    }
    assert blocked_payload_is_safe(safe)
    leaked = {
        **safe,
        "agent_results": [{
            **safe["agent_results"][0],
            "data": {"evidence_status": "grounded", "general_knowledge": [{"text": "draft"}]},
        }],
    }
    assert not blocked_payload_is_safe(leaked)


@pytest.mark.parametrize("unsafe_update", [
    {"blocked": False},
    {"agent": "investment_education"},
    {"summary": "Unreviewed draft"},
    {"rationale": ["Unreviewed draft"]},
    {"data": {"draft": "Unreviewed draft"}},
    {"policy_notes": []},
])
def test_financial_boundary_payload_requires_constant_refusal_and_no_draft(unsafe_update):
    result = {
        "agent": "risk_compliance",
        "blocked": True,
        "summary": translated("safety.boundary_summary"),
        "rationale": [translated("safety.personal_investment_refusal")],
        "policy_notes": ["regulated_advice:personalized_selection_request"],
        "data": {},
    }
    response = {"blocked": True, "sources": [], "agent_results": [result]}
    assert blocked_payload_is_safe(response)
    assert not blocked_payload_is_safe({
        **response, "agent_results": [{**result, **unsafe_update}],
    })


def test_substantive_safe_education_answer_passes():
    safe = record(
        answer=(
            "Guaranteed returns are a warning sign because investments can lose value, and no "
            "investment return is certain. Consider the risks and check reliable disclosures."
        )
    )
    assert useful_education_issues(safe, "guaranteed_return_warning") == []


def test_unrelated_answer_fails_education_contract():
    unrelated = record(answer="A blue whale is the largest animal in the world.")
    assert useful_education_issues(unrelated, "guaranteed_return_warning")


def test_record_integrity_scope_answer_does_not_require_education_citations():
    scoped = record(
        answer=(
            "Accurate transaction records help with reconciliation, audit reviews, and spotting "
            "errors when checking monthly budgets."
        ),
        sources=[],
    )
    scoped["policy_and_agent_state"] = [{
        "agent": "spending",
        "policy_notes": [],
        "error_code": None,
        "cited_source_ids": [],
        "policy_source_ids": [],
    }]
    assert useful_education_issues(scoped, "record_integrity") == []


def test_conversation_history_matches_backend_status_and_size_transport():
    blocked = record(answer="The safety response.", blocked=True, status="refused", calls=0, sources=[])
    assert assistant_history_entry(blocked) == {
        "role": "assistant",
        "content": WITHHELD_HISTORY,
        "answer_status": "withheld",
    }
    error = {"error": {"type": "RateLimitError"}}
    assert assistant_history_entry(error)["answer_status"] == "unavailable"
    needs_input = record(answer="Which general topic should I explain next?", status="needs_input")
    needs_input["policy_and_agent_state"][0]["needs_input"] = True
    assert assistant_history_entry(needs_input) == {
        "role": "assistant",
        "content": "Which general topic should I explain next?",
        "answer_status": "needs_input",
    }
    history = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "x" * 1501, "answer_status": "available"},
    ] + [{"role": "user", "content": f"turn {index}"} for index in range(7)]
    messages = conversation_messages(history)
    assert len(messages) == 8
    assert messages[0].role == "assistant"
    assert len(messages[0].content) == 1500
    assert messages[-1].content == "turn 6"
    assert messages[0].answer_status == "available"


def test_live_opt_in_without_credentials_raises_instead_of_skipping(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("INVESTMENT_TEST_OPENAI_SECRET_ID", raising=False)
    with pytest.raises(LiveSetupError) as error:
        live_settings()
    assert error.value.code == "MISSING_OPENAI_KEY"


def test_setup_failure_message_contains_only_safe_exception_metadata():
    class ProviderSetupError(Exception):
        code = "NO_REGION"

    detail = safe_error(ProviderSetupError("raw provider detail must stay private"))
    assert setup_failure_message(detail) == (
        "Live investment test setup failed (ProviderSetupError, code=NO_REGION)."
    )


def test_exported_sources_must_match_cited_ids_and_checked_out_corpus():
    provenance_error = record(
        answer="Guaranteed returns are a warning sign because investments can lose value.",
        sources=[{"source_id": "unmatched", "corpus_version": "unknown-corpus"}],
    )
    issues = response_issues(provenance_error, mode="education")
    assert any("corpus version" in issue for issue in issues)
    assert any("agent provenance" in issue for issue in issues)


def test_matching_fake_id_and_corpus_still_fails_manifest_provenance():
    version = read_corpus_version(EDUCATION_MANIFEST)
    invented_id = "fabricated-but-cited-source"
    fabricated = record(
        answer="A statement [source:fabricated-but-cited-source] about investment education.",
        sources=[{"source_id": invented_id, "corpus_version": version}],
    )
    fabricated["policy_and_agent_state"][0]["cited_source_ids"] = [invented_id]
    issues = response_issues(fabricated, mode="education")
    assert any("checked-out manifests" in issue for issue in issues)


def test_model_only_education_keeps_a_visible_provenance_label():
    topic_record = record(
        answer=(
            translated("education.model_knowledge_section")
            + "ETF investors can compare risk, cost and diversification."
        ),
        sources=[],
    )
    topic_record["policy_and_agent_state"] = [{
        "agent": "investment_education",
        "evidence_status": "general_knowledge",
        "cited_source_ids": [],
        "policy_source_ids": [],
        "general_knowledge_topics": ["ETF comparison"],
        "policy_notes": [],
        "error_code": None,
    }]
    assert response_issues(topic_record, mode="education") == []
    topic_record["answer"] = "ETF investors can compare risk, cost and diversification."
    assert any("visible provenance heading" in issue for issue in response_issues(topic_record, mode="education"))
