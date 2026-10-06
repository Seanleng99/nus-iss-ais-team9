import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.schemas import ConversationMessage
from app.evals import rag_answer_review as answer_review
from app.evals.rag_answer_review import REVIEW_FIELDS, capture, response_digest, score_reviews
from app.evals.rag_evidence import EvidenceCase

DATASET_DIGEST = sha256(b"dataset").hexdigest()
CORPUS_VERSION = "education-corpus@2026-09-26"
POLICY_CORPUS_VERSION = "policy-corpus@2026-09-26"


def example(profile="bedrock_v7", *, auto_route=False):
    if profile == "bedrock_v7":
        providers = {"model": "bedrock", "education": "bedrock", "policy": "bedrock"}
        model_id, prompt_version = "apac.amazon.nova-lite-v1:0", "v7"
    else:
        providers = {"model": "openai", "education": "local_documents", "policy": "local_documents"}
        model_id, prompt_version = "gpt-6-luna", "v6"
    selected_agents = ["budget"] if auto_route else ["investment_education"]
    education_data = {"evidence_status": "insufficient", "unanswered_topics": []}
    cases, rows = [], []
    for language in ("en", "zh"):
        case = EvidenceCase(
            id=language,
            family="missing-evidence",
            split="development",
            language=language,
            question="Explain missing evidence",
            expected_status="insufficient",
            required_evidence=[],
            answer_rubric=["State the evidence gap", "Do not imply a verified answer"],
            unanswered_topics=[],
        )
        response = {
            "answer": "Evidence unavailable",
            "sources": [],
            "blocked": False,
            "selected_agents": selected_agents,
            "agent_results": (
                [{"agent": "investment_education", "data": education_data}]
                if not auto_route
                else []
            ),
            "audit": {
                "model_provider": providers["model"],
                "prompt_set_version": prompt_version,
                "model_id": model_id,
            },
        }
        digest = response_digest(response)
        rows.append(
            {
                "case_id": case.id,
                "repeat": 0,
                "dataset_sha256": DATASET_DIGEST,
                "corpus_version": CORPUS_VERSION,
                "policy_corpus_version": POLICY_CORPUS_VERSION,
                "profile": profile,
                "providers": providers,
                "model_id": model_id,
                "prompt_set_version": prompt_version,
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
        cases.append(case)
    return cases, rows


@pytest.mark.parametrize("profile", ["bedrock_v7", "openai_local_v6"])
def test_review_accepts_only_supported_real_model_profiles(profile):
    cases, rows = example(profile)
    report = score_reviews(
        rows,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        expected_model_id=rows[0]["model_id"],
        profile=profile,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert report["answer_gate_passed"]
    assert report["profile"] == profile


@pytest.mark.parametrize("field", ["complete", "rubric_matched", "routing_correct"])
def test_completeness_rubric_and_automatic_routing_are_independent_review_gates(field):
    cases, rows = example("openai_local_v6", auto_route=True)
    assert {"complete", "rubric_matched", "routing_correct"}.issubset(REVIEW_FIELDS)
    rows[0]["review"][field] = False
    report = score_reviews(
        rows,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        profile="openai_local_v6",
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert not report["answer_gate_passed"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", "gpt-6-sol"),
        ("prompt_set_version", "v7"),
        ("profile", "bedrock_v7"),
        ("corpus_version", "other-corpus@v1"),
        ("policy_corpus_version", "other-policy@v1"),
    ],
)
def test_review_rejects_metadata_that_does_not_match_the_expected_run(field, value):
    cases, rows = example("openai_local_v6")
    rows[0][field] = value
    with pytest.raises(ValueError, match="metadata"):
        score_reviews(
            rows,
            cases,
            DATASET_DIGEST,
            CORPUS_VERSION,
            repeats=1,
            profile="openai_local_v6",
            policy_corpus_version=POLICY_CORPUS_VERSION,
        )


@pytest.mark.parametrize(
    ("provider_key", "value"),
    [("model", "local_fixture"), ("education", "local_fixture"), ("policy", "local_fixture")],
)
def test_review_rejects_fixture_or_wrong_provider_per_component(provider_key, value):
    cases, rows = example("openai_local_v6")
    rows[0]["providers"][provider_key] = value
    with pytest.raises(ValueError, match="metadata"):
        score_reviews(
            rows,
            cases,
            DATASET_DIGEST,
            CORPUS_VERSION,
            repeats=1,
            profile="openai_local_v6",
            policy_corpus_version=POLICY_CORPUS_VERSION,
        )


def test_review_rejects_wrong_dataset_digest_and_unreviewed_response_digest():
    cases, rows = example("openai_local_v6")
    altered = deepcopy(rows)
    altered[0]["dataset_sha256"] = sha256(b"different dataset").hexdigest()
    with pytest.raises(ValueError, match="dataset digest"):
        score_reviews(
            altered,
            cases,
            DATASET_DIGEST,
            CORPUS_VERSION,
            repeats=1,
            profile="openai_local_v6",
            policy_corpus_version=POLICY_CORPUS_VERSION,
        )

    altered = deepcopy(rows)
    altered[0]["reviewed_response_sha256"] = "0" * 64
    report = score_reviews(
        altered,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        profile="openai_local_v6",
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert not report["answer_gate_passed"]


def test_failed_or_missing_runs_cannot_be_deleted_to_raise_the_score():
    cases, rows = example()
    for altered in [rows[:0], rows + rows]:
        with pytest.raises(ValueError, match="exactly once"):
            score_reviews(altered, cases, DATASET_DIGEST, CORPUS_VERSION, repeats=1)


def test_review_cannot_change_question_or_answer_rubric():
    for field, value in (("question", "Changed question"), ("answer_rubric", ["Always pass"])):
        cases, rows = example()
        rows[0][field] = value
        with pytest.raises(ValueError, match="annotation"):
            score_reviews(rows, cases, DATASET_DIGEST, CORPUS_VERSION, repeats=1)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reviewer", ""),
        ("reviewed_response_sha256", ""),
        ("error", "ProviderFailure"),
    ],
)
def test_review_requires_reviewer_and_response_digest_and_successful_capture(field, value):
    cases, rows = example()
    rows[0][field] = value
    report = score_reviews(
        rows,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert not report["answer_gate_passed"]


@pytest.mark.parametrize("value", [None, "true", 1, False])
def test_review_fields_must_be_explicit_booleans(value):
    cases, rows = example()
    rows[0]["review"]["grounded"] = value
    report = score_reviews(
        rows,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert not report["answer_gate_passed"]


def test_response_digest_is_bound_to_reviewed_content():
    cases, rows = example()
    rows[0]["response"]["answer"] = "Changed after review"
    report = score_reviews(
        rows,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert not report["answer_gate_passed"]


@pytest.mark.parametrize(
    ("audit_field", "value"),
    [
        ("model_provider", "local_fixture"),
        ("model_id", "apac.amazon.nova-pro-v1:0"),
        ("prompt_set_version", "v6"),
    ],
)
def test_review_rejects_response_audit_identity_mismatch(audit_field, value):
    cases, rows = example()
    rows[0]["response"]["audit"][audit_field] = value
    digest = response_digest(rows[0]["response"])
    rows[0]["response_sha256"] = digest
    rows[0]["reviewed_response_sha256"] = digest
    report = score_reviews(
        rows,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert not report["answer_gate_passed"]


def test_capture_uses_automatic_routing_and_records_openai_local_v6(tmp_path, monkeypatch):
    observed = {}

    class FakeOrchestrator:
        def __init__(self, *, config):
            observed["config"] = config

        def handle(self, request):
            observed["request"] = request
            return type(
                "Response",
                (),
                {
                    "model_dump": lambda self, mode: {
                        "answer": "A budget response",
                        "sources": [],
                        "blocked": False,
                        "selected_agents": ["budget"],
                        "agent_results": [],
                        "audit": {
                            "model_provider": "openai",
                            "prompt_set_version": "v6",
                            "model_id": "gpt-6-luna",
                        },
                    }
                },
            )()

    monkeypatch.setattr("app.evals.rag_answer_review.AgentOrchestrator", FakeOrchestrator)
    config = Settings(
        MODEL_PROVIDER="openai",
        MODEL_ID="gpt-6-luna",
        RAG_PROVIDER="local_documents",
        POLICY_RAG_PROVIDER="local_documents",
        PROMPT_SET_VERSION="v6",
        EDUCATION_CORPUS_VERSION=CORPUS_VERSION,
        POLICY_CORPUS_VERSION=POLICY_CORPUS_VERSION,
    )
    cases, _ = example("openai_local_v6")
    output = tmp_path / "capture.jsonl"
    capture(
        cases,
        config,
        DATASET_DIGEST,
        output,
        repeats=1,
        profile="openai_local_v6",
        corpus_version=CORPUS_VERSION,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert observed["request"].requested_agents is None
    row = json.loads(output.read_text().splitlines()[0])
    assert row["profile"] == "openai_local_v6"
    assert row["providers"] == {
        "model": "openai",
        "education": "local_documents",
        "policy": "local_documents",
    }
    assert row["model_id"] == "gpt-6-luna"
    assert row["prompt_set_version"] == "v6"
    assert row["corpus_version"] == CORPUS_VERSION
    assert row["policy_corpus_version"] == POLICY_CORPUS_VERSION


def test_capture_still_accepts_default_bedrock_v7_profile(tmp_path, monkeypatch):
    class FakeOrchestrator:
        def __init__(self, *, config):
            pass

        def handle(self, request):
            return type(
                "Response",
                (),
                {
                    "model_dump": lambda self, mode: {
                        "answer": "ok",
                        "sources": [],
                        "audit": {
                            "model_provider": "bedrock",
                            "prompt_set_version": "v7",
                            "model_id": "apac.amazon.nova-lite-v1:0",
                        },
                    }
                },
            )()

    monkeypatch.setattr("app.evals.rag_answer_review.AgentOrchestrator", FakeOrchestrator)
    config = Settings(
        MODEL_PROVIDER="bedrock",
        MODEL_ID="apac.amazon.nova-lite-v1:0",
        RAG_PROVIDER="bedrock",
        POLICY_RAG_PROVIDER="bedrock",
        PROMPT_SET_VERSION="v7",
        EDUCATION_CORPUS_VERSION=CORPUS_VERSION,
    )
    cases, _ = example()
    output = tmp_path / "capture.jsonl"
    capture(cases, config, DATASET_DIGEST, output, repeats=1, corpus_version=CORPUS_VERSION)
    captured = [json.loads(line) for line in output.read_text().splitlines()]
    assert captured[0]["profile"] == "bedrock_v7"


@pytest.mark.parametrize("profile", ["openai_local_v6", "bedrock_v7"])
def test_capture_refuses_profile_mismatch_without_writing_output(tmp_path, profile):
    config = Settings(MODEL_PROVIDER="local_fixture")
    output = tmp_path / "capture.jsonl"
    with pytest.raises(ValueError, match="profile"):
        capture([], config, DATASET_DIGEST, output, repeats=1, profile=profile)
    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MODEL_ID", "gpt-6-sol"),
        ("RAG_PROVIDER", "bedrock"),
        ("POLICY_RAG_PROVIDER", "bedrock"),
        ("PROMPT_SET_VERSION", "v7"),
        ("EDUCATION_CORPUS_VERSION", "other-education@v1"),
        ("POLICY_CORPUS_VERSION", "other-policy@v1"),
    ],
)
def test_capture_validates_every_configured_component_before_writing(tmp_path, field, value):
    config_values = {
        "MODEL_PROVIDER": "openai",
        "MODEL_ID": "gpt-6-luna",
        "RAG_PROVIDER": "local_documents",
        "POLICY_RAG_PROVIDER": "local_documents",
        "PROMPT_SET_VERSION": "v6",
        "EDUCATION_CORPUS_VERSION": CORPUS_VERSION,
        "POLICY_CORPUS_VERSION": POLICY_CORPUS_VERSION,
    }
    config_values[field] = value
    config = Settings(**config_values)
    cases, _ = example("openai_local_v6")
    output = tmp_path / "capture.jsonl"
    with pytest.raises(ValueError):
        capture(
            cases,
            config,
            DATASET_DIGEST,
            output,
            repeats=1,
            profile="openai_local_v6",
            corpus_version=CORPUS_VERSION,
            policy_corpus_version=POLICY_CORPUS_VERSION,
        )
    assert not output.exists()


def test_review_rejects_mixed_policy_corpus_versions():
    cases, rows = example()
    rows[1]["policy_corpus_version"] = "different-policy@v1"
    with pytest.raises(ValueError, match="policy corpus"):
        score_reviews(rows, cases, DATASET_DIGEST, CORPUS_VERSION, repeats=1)


def test_unsafe_and_incomplete_reviews_fail_separately():
    cases, rows = example("openai_local_v6")
    rows[0]["review"]["safe"] = False
    report = score_reviews(
        rows,
        cases,
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        profile="openai_local_v6",
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert report["safe_rate"] == 0.5
    assert not report["answer_gate_passed"]


def test_missing_language_still_fails_the_bilingual_release_gate():
    cases, rows = example()
    report = score_reviews(
        rows[:1],
        cases[:1],
        DATASET_DIGEST,
        CORPUS_VERSION,
        repeats=1,
        profile="bedrock_v7",
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert report["by_language"] == {"en": 1.0, "zh": None}
    assert not report["answer_gate_passed"]


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_frozen_answerability_dataset_has_balanced_coverage_and_pinned_hashes(version):
    dataset = (
        Path(__file__).resolve().parents[1] / f"app/evals/datasets/investment_answerability_{version}.jsonl"
    )
    manifest_path = dataset.with_suffix(".manifest.json")
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(rows) == 280
    assert len({row["id"] for row in rows}) == 280
    assert manifest["dataset_sha256"] == sha256(dataset.read_bytes()).hexdigest()
    holdout_bytes = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
        if row["split"] == "holdout"
    ).encode("utf-8")
    assert manifest["holdout_sha256"] == sha256(holdout_bytes).hexdigest()
    assert manifest["row_count"] == 280
    assert Counter((row["kind"], row["language"]) for row in rows) == {
        ("quality", "en"): 100,
        ("quality", "zh"): 100,
        ("safety", "en"): 40,
        ("safety", "zh"): 40,
    }
    family_splits = {}
    for row in rows:
        family_splits.setdefault(row["family"], set()).add(row["split"])
        assert row["expected_outcome"] in {"answer", "partial", "clarify", "refuse"}
        assert row["turns"] and row["answer_rubric"] and row["forbidden_behaviors"]
        assert isinstance(row["known_regression"], bool) and row["origin"]
    assert all(len(splits) == 1 for splits in family_splits.values())
    assert (
        len(
            {
                row["family"]
                for row in rows
                if row["kind"] == "quality" and row["split"] == "holdout"
            }
        )
        >= 40
    )
    assert manifest["family_counts_by_kind_split"] == {
        "quality:development": 60,
        "quality:holdout": 40,
        "safety:development": 20,
        "safety:holdout": 20,
    }
    assert all(row["expected_outcome"] == "refuse" for row in rows if row["kind"] == "safety")
    for number in range(1, 31):
        assert any(f"beginner-{number:02d}" in row["origin"] for row in rows)
    for number in range(1, 23):
        assert any(f"audit:a{number:02d}" in row["origin"] for row in rows)


def answerability_cases(split="development"):
    answerability_case = answer_review.AnswerabilityCase
    cases = []
    for kind, language in (("quality", "en"), ("quality", "zh"), ("safety", "en"), ("safety", "zh")):
        family = f"{kind}-pair"
        outcome = "answer" if kind == "quality" else "refuse"
        cases.append(
            answerability_case(
                id=f"{family}-{language}",
                kind=kind,
                family=family,
                split=split,
                language=language,
                turns=["first turn", "follow-up"],
                expected_outcome=outcome,
                answer_rubric=["Cover the requested concept"],
                forbidden_behaviors=["Do not invent current facts"],
                known_regression=language == "en",
                origin="synthetic-test",
            )
        )
    return cases


def full_answerability_cases():
    cases = []
    for kind, split, families in (
        ("quality", "development", 60),
        ("quality", "holdout", 40),
        ("safety", "development", 20),
        ("safety", "holdout", 20),
    ):
        for family_number in range(families):
            family = f"{kind}-{split}-{family_number:03d}"
            for language in ("en", "zh"):
                cases.append(
                    answer_review.AnswerabilityCase(
                        id=f"{family}-{language}",
                        kind=kind,
                        family=family,
                        split=split,
                        language=language,
                        turns=["synthetic evaluation request"],
                        expected_outcome="refuse" if kind == "safety" else "answer",
                        answer_rubric=["Meet the synthetic rubric"],
                        forbidden_behaviors=["Do not invent facts"],
                        known_regression=False,
                        origin="generated-test-matrix",
                    )
                )
    return cases


def answerability_identity(profile="openai_local_v6"):
    identity = answer_review._profile(profile)
    return {
        "profile": profile,
        "providers": identity["providers"],
        "runtime_config": answer_review.OPENAI_LOCAL_V6_RUNTIME_CONFIG,
        "model_id": identity["model_id"],
        "prompt_set_version": identity["prompt_set_version"],
        "corpus_version": CORPUS_VERSION,
        "policy_corpus_version": POLICY_CORPUS_VERSION,
        "prompt_file_hashes": answer_review._prompt_file_hashes(identity["prompt_set_version"]),
    }


def answerability_rows(cases, *, candidate_sha256="a" * 64, dataset_digest=DATASET_DIGEST):
    rows = []
    identity = answerability_identity()
    for case in cases:
        blocked = case.kind == "safety"
        for repeat in range(3):
            turns = [
                {
                    "index": index,
                    "message": turn,
                    "response": {
                        "answer": "I cannot help execute that request." if blocked else "Concept explanation.",
                        "blocked": blocked,
                        "sources": [],
                        "selected_agents": [] if blocked else ["investment_education"],
                        # The reviewer decision must not be inferred from this agent field.
                        "agent_results": [{"agent": "risk_compliance", "data": {"blocked": not blocked}}],
                        "audit": {
                            "model_provider": "openai",
                            "prompt_set_version": "v6",
                            "model_id": "gpt-6-luna",
                        },
                    },
                    "error": None,
                    "elapsed_ms": 1,
                }
                for index, turn in enumerate(case.turns)
            ]
            for turn in turns:
                turn["response_sha256"] = response_digest(turn["response"])
            response = turns[-1]["response"]
            conversation_hash = answer_review.response_digest(
                {"turn_results": turns, "final_response": response}
            )
            row = {
                **case.model_dump(mode="json"),
                **identity,
                "repeat": repeat,
                "dataset_sha256": dataset_digest,
                "candidate_sha256": candidate_sha256,
                "turn_results": turns,
                "final_response": response,
                "final_response_sha256": response_digest(response),
                "response_sha256": conversation_hash,
                "elapsed_ms": 2,
                "reviewer": "Alex Reviewer",
                "review_mode": "human",
                "review_assistant": "",
                "reviewed_response_sha256": conversation_hash,
                "review": dict.fromkeys(answer_review.ANSWERABILITY_REVIEW_FIELDS, True),
            }
            rows.append(row)
    return rows


def test_answerability_case_is_frozen_strict_and_loader_can_filter_development(tmp_path):
    cases = answerability_cases()
    raw = [case.model_dump(mode="json") for case in cases]
    raw[0]["unexpected"] = "extra"
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("\n".join(json.dumps(case) for case in raw), encoding="utf-8")
    with pytest.raises(ValueError):
        answer_review.load_answerability_cases(dataset)

    dataset.write_text("\n".join(json.dumps(case) for case in [c.model_dump(mode="json") for c in cases]), encoding="utf-8")
    assert len(answer_review.load_answerability_cases(dataset, split="development")) == 4
    with pytest.raises(ValueError):
        cases[0].expected_outcome = "refuse"


def test_capture_answerability_forwards_bounded_multiturn_context_without_forcing_agents(
    tmp_path, monkeypatch
):
    observed = []

    class FakeOrchestrator:
        def __init__(self, *, config):
            self.calls = 0
            observed.append(self)

        def handle(self, request):
            self.calls += 1
            observed.append(request)
            return type(
                "Response",
                (),
                {
                    "model_dump": lambda self, mode: {
                        "answer": "A" * 1800,
                        "blocked": False,
                        "sources": [],
                        "selected_agents": ["investment_education"],
                        "audit": {
                            "model_provider": "openai",
                            "prompt_set_version": "v6",
                            "model_id": "gpt-6-luna",
                        },
                    }
                },
            )()

    monkeypatch.setattr(answer_review, "AgentOrchestrator", FakeOrchestrator)
    config = Settings(
        _env_file=None,
        MODEL_PROVIDER="openai", MODEL_ID="gpt-6-luna", RAG_PROVIDER="local_documents",
        POLICY_RAG_PROVIDER="local_documents", PROMPT_SET_VERSION="v6",
        EDUCATION_CORPUS_VERSION=CORPUS_VERSION, POLICY_CORPUS_VERSION=POLICY_CORPUS_VERSION,
        MAX_MODEL_TOKENS_PER_RUN=20000,
        AGENT_TIMEOUT_SECONDS=20,
        MODEL_READ_TIMEOUT_SECONDS=15,
        MODEL_REASONING_EFFORT="low", MODEL_MAX_TOKENS=1600, MODEL_ROLE_OVERRIDES={},
    )
    case = answer_review.AnswerabilityCase(
        id="long-en", kind="quality", family="long", split="development", language="en",
        turns=[f"turn {i}" for i in range(7)], expected_outcome="answer",
        answer_rubric=["Explain clearly"], forbidden_behaviors=["Do not fabricate"],
        known_regression=False, origin="synthetic",
    )
    output = tmp_path / "answerability.jsonl"
    answer_review.capture_answerability(
        [case], config, DATASET_DIGEST, output, repeats=2, workers=1,
        candidate_sha256="b" * 64, corpus_version=CORPUS_VERSION,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    requests = [item for item in observed if hasattr(item, "conversation_context")]
    assert len(requests) == 14
    assert all(request.requested_agents is None for request in requests)
    assert len(requests[-1].conversation_context) == 8
    assert all(len(message.content) <= 1500 for message in requests[-1].conversation_context)
    assert isinstance(requests[-1].conversation_context[0], ConversationMessage)
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 2
    assert all(len(record["turn_results"]) == 7 for record in records)
    assert all(record["reviewer"] == "" for record in records)
    assert all(record["reviewed_response_sha256"] == "" for record in records)
    assert all(record["split"] == "development" for record in records)
    assert all(record["final_response_sha256"] == response_digest(record["final_response"]) for record in records)


def test_capture_answerability_rejects_runtime_mismatch_and_worker_overflow(tmp_path):
    case = answerability_cases()[0]
    config = Settings(
        MODEL_PROVIDER="openai", MODEL_ID="gpt-6-luna", RAG_PROVIDER="local_documents",
        POLICY_RAG_PROVIDER="local_documents", PROMPT_SET_VERSION="v6",
        EDUCATION_CORPUS_VERSION=CORPUS_VERSION, POLICY_CORPUS_VERSION=POLICY_CORPUS_VERSION,
        MODEL_MAX_TOKENS=1700,
    )
    with pytest.raises(ValueError, match="runtime"):
        answer_review.capture_answerability(
            [case], config, DATASET_DIGEST, tmp_path / "runtime.jsonl",
            candidate_sha256="b" * 64,
        )
    config = Settings(
        MODEL_PROVIDER="openai", MODEL_ID="gpt-6-luna", RAG_PROVIDER="local_documents",
        POLICY_RAG_PROVIDER="local_documents", PROMPT_SET_VERSION="v6",
        EDUCATION_CORPUS_VERSION=CORPUS_VERSION, POLICY_CORPUS_VERSION=POLICY_CORPUS_VERSION,
    )
    with pytest.raises(ValueError, match="workers"):
        answer_review.capture_answerability(
            [case], config, DATASET_DIGEST, tmp_path / "workers.jsonl", workers=9,
            candidate_sha256="b" * 64,
        )
    with pytest.raises(ValueError, match="fixed"):
        answer_review.capture_answerability(
            [case], config, DATASET_DIGEST, tmp_path / "override.jsonl",
            candidate_sha256="b" * 64,
            expected_runtime_config={
                **answer_review.OPENAI_LOCAL_V6_RUNTIME_CONFIG,
                "model_max_tokens": 4096,
            },
        )


def test_frozen_v6_capture_rejects_active_app_role_policies(tmp_path):
    config = Settings(
        _env_file=None, MODEL_PROVIDER="openai", MODEL_ID="gpt-6-luna",
        RAG_PROVIDER="local_documents", POLICY_RAG_PROVIDER="local_documents",
        PROMPT_SET_VERSION="v6", EDUCATION_CORPUS_VERSION=CORPUS_VERSION,
        POLICY_CORPUS_VERSION=POLICY_CORPUS_VERSION,
        **{name.upper(): setting for name, setting in answer_review.OPENAI_LOCAL_V6_RUNTIME_CONFIG.items()},
    )
    with pytest.raises(ValueError, match="MODEL_ROLE_OVERRIDES"):
        answer_review.capture_answerability(
            [answerability_cases()[0]], config, DATASET_DIGEST, tmp_path / "frozen.jsonl",
            candidate_sha256="b" * 64,
        )


def test_full_answerability_positive_matrix_uses_case_row_split_counts_without_dataset_reads():
    cases = full_answerability_cases()
    rows = answerability_rows(cases)
    report = answer_review.score_answerability_reviews(
        rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert len(cases) == 280
    assert len(rows) == 840
    assert report["answerability_gate_passed"]
    assert report["quality"]["by_language"] == {"en": 1.0, "zh": 1.0}
    assert report["safety"]["failures"] == 0

    unsafe_review_rows = deepcopy(rows)
    unsafe_review_rows[0]["review"]["safe"] = False
    unsafe_report = answer_review.score_answerability_reviews(
        unsafe_review_rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert unsafe_report["quality"]["accuracy"] > 0.99
    assert unsafe_report["safety"]["unsafe_reviews_across_all_runs"] == 1
    assert not unsafe_report["answerability_gate_passed"]


def test_only_final_turn_outcome_is_required_for_multiturn_quality_and_safety():
    cases = answerability_cases()
    rows = answerability_rows(cases)
    quality_row = rows[0]
    quality_row["turn_results"][0]["response"]["blocked"] = True
    quality_row["turn_results"][0]["response"]["selected_agents"] = []
    safety_row = rows[6]
    safety_row["turn_results"][0]["response"].update(
        blocked=False, answer="General educational context.", selected_agents=["investment_education"]
    )
    for row in rows:
        for turn in row["turn_results"]:
            turn["response_sha256"] = response_digest(turn["response"])
        row["final_response"] = row["turn_results"][-1]["response"]
        row["final_response_sha256"] = response_digest(row["final_response"])
        row["response_sha256"] = answer_review.response_digest(
            {"turn_results": row["turn_results"], "final_response": row["final_response"]}
        )
        row["reviewed_response_sha256"] = row["response_sha256"]
    report = answer_review.score_answerability_reviews(
        rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
        split="development",
    )
    assert report["smoke_passed"]


def test_capture_answerability_omits_blocked_assistant_from_followup_context(tmp_path, monkeypatch):
    seen = []

    class FakeOrchestrator:
        def __init__(self, *, config):
            self.index = 0

        def handle(self, request):
            seen.append(request)
            self.index += 1
            blocked = self.index == 1
            return type(
                "Response",
                (),
                {
                    "model_dump": lambda self, mode: {
                        "answer": "secret text" if blocked else "Friendly refusal.",
                        "blocked": blocked,
                        "sources": [],
                        "selected_agents": ["risk_compliance"],
                        "audit": {
                            "model_provider": "openai",
                            "prompt_set_version": "v6",
                            "model_id": "gpt-6-luna",
                        },
                    }
                },
            )()

    monkeypatch.setattr(answer_review, "AgentOrchestrator", FakeOrchestrator)
    config = Settings(
        _env_file=None,
        MODEL_PROVIDER="openai", MODEL_ID="gpt-6-luna", RAG_PROVIDER="local_documents",
        POLICY_RAG_PROVIDER="local_documents", PROMPT_SET_VERSION="v6",
        EDUCATION_CORPUS_VERSION=CORPUS_VERSION, POLICY_CORPUS_VERSION=POLICY_CORPUS_VERSION,
        MAX_MODEL_TOKENS_PER_RUN=20000,
        AGENT_TIMEOUT_SECONDS=20,
        MODEL_READ_TIMEOUT_SECONDS=15,
        MODEL_REASONING_EFFORT="low", MODEL_MAX_TOKENS=1600, MODEL_ROLE_OVERRIDES={},
    )
    case = answer_review.AnswerabilityCase(
        id="safe-en", kind="safety", family="safe", split="development", language="en",
        turns=["unsafe request", "repeat request"], expected_outcome="refuse",
        answer_rubric=["Refuse and redirect"], forbidden_behaviors=["Do not comply"],
        known_regression=False, origin="synthetic",
    )
    output = tmp_path / "blocked.jsonl"
    answer_review.capture_answerability(
        [case], config, DATASET_DIGEST, output, repeats=1, workers=1,
        candidate_sha256="c" * 64, corpus_version=CORPUS_VERSION,
        policy_corpus_version=POLICY_CORPUS_VERSION,
    )
    assert seen[1].conversation_context[-1].content == answer_review.BLOCKED_CONTEXT_OMISSION
    assert "secret text" not in seen[1].conversation_context[-1].content


def test_score_answerability_smoke_separates_quality_and_safety_and_requires_all_cases():
    cases = answerability_cases()
    rows = answerability_rows(cases)
    report = answer_review.score_answerability_reviews(
        rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
        split="development",
    )
    assert report["smoke_passed"]
    assert not report["answerability_gate_passed"]
    assert report["quality"]["runs"] == 6
    assert report["quality"]["by_language"] == {"en": 1.0, "zh": 1.0}
    assert report["safety"]["passed_runs"] == 6
    with pytest.raises(ValueError, match="exactly once"):
        answer_review.score_answerability_reviews(
            rows[:-1], cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
            repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
            split="development",
        )
    with pytest.raises(ValueError, match="exactly once"):
        answer_review.score_answerability_reviews(
            rows + rows[:1], cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
            repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
            split="development",
        )


@pytest.mark.parametrize("problem", ["blocked_quality", "unblocked_safety", "unreviewed", "unsafe_refusal"])
def test_score_answerability_never_passes_blocked_quality_or_unsafe_safety(problem):
    cases = answerability_cases()
    rows = answerability_rows(cases)
    if problem == "blocked_quality":
        rows[0]["turn_results"][-1]["response"]["blocked"] = True
    elif problem == "unblocked_safety":
        rows[6]["turn_results"][-1]["response"]["blocked"] = False
    elif problem == "unreviewed":
        rows[0]["reviewer"] = ""
    else:
        rows[4]["review"]["safe"] = False
        rows[4]["turn_results"][-1]["response"]["sources"] = [{"source_id": "unexpected", "corpus_version": CORPUS_VERSION}]
    for row in rows:
        turn_responses = [turn["response"] for turn in row["turn_results"]]
        row["final_response"] = turn_responses[-1]
        row["final_response_sha256"] = response_digest(row["final_response"])
        row["response_sha256"] = answer_review.response_digest(
            {"turn_results": row["turn_results"], "final_response": row["final_response"]}
        )
        if row["reviewer"]:
            row["reviewed_response_sha256"] = row["response_sha256"]
    report = answer_review.score_answerability_reviews(
        rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
        split="development",
    )
    assert not report["smoke_passed"]


def test_full_answerability_scorer_rejects_smoke_cases_and_identity_or_hash_mismatch():
    cases = answerability_cases()
    rows = answerability_rows(cases)
    with pytest.raises(ValueError, match="complete frozen answerability set"):
        answer_review.score_answerability_reviews(
            rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
            repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
        )
    for key, value in (
        ("candidate_sha256", "d" * 64),
        ("dataset_sha256", sha256(b"other").hexdigest()),
        ("prompt_set_version", "v7"),
        ("runtime_config", {**answer_review.OPENAI_LOCAL_V6_RUNTIME_CONFIG, "model_max_tokens": 999}),
    ):
        altered = deepcopy(rows)
        altered[0][key] = value
        with pytest.raises(ValueError):
            answer_review.score_answerability_reviews(
                altered, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
                repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
                split="development",
            )
    altered = deepcopy(rows)
    altered[0]["prompt_file_hashes"]["prompts.json"] = "0" * 64
    with pytest.raises(ValueError, match="identity or pinned hashes"):
        answer_review.score_answerability_reviews(
            altered, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
            repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
            split="development",
        )
    altered = deepcopy(rows)
    altered[0]["response_sha256"] = "0" * 64
    report = answer_review.score_answerability_reviews(
        altered, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        repeats=3, profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
        split="development",
    )
    assert not report["smoke_passed"]


def test_review_attribution_requires_named_reviewer_and_labels_model_assistance():
    cases = answerability_cases()
    rows = answerability_rows(cases)
    rows[0]["reviewer"] = "Reviewer"
    report = answer_review.score_answerability_reviews(
        rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
        split="development",
    )
    assert report["reviewed_runs"] == len(rows) - 1
    assert not report["smoke_passed"]

    rows = answerability_rows(cases)
    rows[0]["review_mode"] = "model_assisted"
    rows[0]["review_assistant"] = "Evaluation model v1"
    report = answer_review.score_answerability_reviews(
        rows, cases, DATASET_DIGEST, "a" * 64, CORPUS_VERSION,
        profile="openai_local_v6", policy_corpus_version=POLICY_CORPUS_VERSION,
        split="development",
    )
    assert report["smoke_passed"]
    assert report["review_modes"]["labeled_model_assisted"] == 1


def test_review_requires_exactly_one_row_for_every_repeat():
    cases, rows = example()
    with pytest.raises(ValueError, match="exactly once"):
        score_reviews(rows, cases, DATASET_DIGEST, CORPUS_VERSION, repeats=2)
