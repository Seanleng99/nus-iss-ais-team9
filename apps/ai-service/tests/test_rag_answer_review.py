from copy import deepcopy

import pytest

from app.core.config import Settings
from app.evals.rag_answer_review import REVIEW_FIELDS, capture, response_digest, score_reviews
from app.evals.rag_evidence import EvidenceCase


def example():
    cases = [
        EvidenceCase(
            id=lang,
            family=lang,
            split="development",
            language=lang,
            question="Explain missing evidence",
            expected_status="insufficient",
            required_evidence=[],
            answer_rubric=["State gap"],
            unanswered_topics=[],
        )
        for lang in ["en", "zh"]
    ]
    rows = []
    for case in cases:
        response = {
            "answer": "Evidence unavailable",
            "sources": [],
            "blocked": False,
            "agent_results": [
                {"agent": "investment_education", "data": {"evidence_status": "insufficient"}}
            ],
            "audit": {"model_provider": "bedrock", "prompt_set_version": "v6"},
        }
        digest = response_digest(response)
        rows.append(
            {
                "case_id": case.id,
                "repeat": 0,
                "dataset_sha256": "dataset",
                "providers": {"model": "bedrock", "education": "bedrock", "policy": "bedrock"},
                "question": case.question,
                "expected_status": case.expected_status,
                "required_evidence": [],
                "unanswered_topics": [],
                "answer_rubric": case.answer_rubric,
                "reviewer": "synthetic-test-reviewer",
                "response": response,
                "response_sha256": digest,
                "reviewed_response_sha256": digest,
                "review": dict.fromkeys(REVIEW_FIELDS, True),
                "error": None,
            }
        )
    return cases, rows


def test_review_requires_complete_explicit_scores_and_real_model_evidence():
    cases, rows = example()
    assert score_reviews(rows, cases, "dataset", "corpus", repeats=1)["answer_gate_passed"]
    for field, value in [
        ("reviewer", ""),
        ("reviewed_response_sha256", ""),
        ("error", "ProviderFailure"),
    ]:
        altered = deepcopy(rows)
        altered[0][field] = value
        assert not score_reviews(altered, cases, "dataset", "corpus", repeats=1)[
            "answer_gate_passed"
        ]
    for value in [None, "true", 1, False]:
        altered = deepcopy(rows)
        altered[0]["review"]["grounded"] = value
        assert not score_reviews(altered, cases, "dataset", "corpus", repeats=1)[
            "answer_gate_passed"
        ]
    altered = deepcopy(rows)
    altered[0]["response"]["audit"]["model_provider"] = "local_fixture"
    digest = response_digest(altered[0]["response"])
    altered[0].update(response_sha256=digest, reviewed_response_sha256=digest)
    assert not score_reviews(altered, cases, "dataset", "corpus", repeats=1)["answer_gate_passed"]


def test_failed_or_missing_runs_cannot_be_deleted_to_raise_the_score():
    cases, rows = example()
    for altered in [rows[:1], rows + rows[:1]]:
        with pytest.raises(ValueError, match="exactly once"):
            score_reviews(altered, cases, "dataset", "corpus", repeats=1)


def test_review_cannot_be_reused_after_answer_changes():
    cases, rows = example()
    rows[0]["response"]["answer"] = "Fabricated new answer"
    assert not score_reviews(rows, cases, "dataset", "corpus", repeats=1)["answer_gate_passed"]


def test_review_cannot_change_the_question_or_ground_truth():
    cases, rows = example()
    rows[0]["answer_rubric"] = ["Always pass"]
    with pytest.raises(ValueError, match="annotation"):
        score_reviews(rows, cases, "dataset", "corpus", repeats=1)


def test_capture_refuses_simulated_generation(tmp_path):
    with pytest.raises(ValueError, match="real Bedrock"):
        capture(
            [],
            Settings(MODEL_PROVIDER="local_fixture"),
            "dataset",
            tmp_path / "fake.jsonl",
            repeats=3,
        )


def test_unsafe_answer_fails_even_when_aggregate_accuracy_could_be_high():
    cases, rows = example()
    rows[0]["review"]["safe"] = False
    report = score_reviews(rows, cases, "dataset", "corpus", repeats=1)
    assert report["safe_rate"] == 0.5
    assert not report["answer_gate_passed"]
