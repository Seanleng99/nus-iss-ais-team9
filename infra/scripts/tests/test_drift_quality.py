import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra.scripts import drift_quality, live_evaluation, model_drift


def case():
    return {"id": "test", "category": "routing", "specialist": "budget", "language": "en", "intent": "calculation",
            "request": {"message": "PRIVATE-SYNTHETIC-QUESTION", "snapshot": {}},
            "expected": {"blocked": False}, "rubric": ["Check only supplied facts."],
            "quality_metrics": ["safe", "helpful", "language_correct"]}


def client_factory(output=None, **overrides):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        required = json.loads(kwargs["input"])["required_metrics"]
        scores = {metric: True if metric in required else None for metric in model_drift.METRICS}
        return SimpleNamespace(status="completed", usage=SimpleNamespace(input_tokens=100, output_tokens=10),
                               model="judge-version", output_text=json.dumps(scores) if output is None else output,
                               **overrides)
    return SimpleNamespace(responses=SimpleNamespace(create=create)), calls


def judge(client):
    return drift_quality.QualityJudge(client, "independent-judge", 1, 1, 0.5, {})


def response():
    from app.core.prompts import CURRENT_PROMPT_VERSION, PromptCatalog

    return {"answer": "PRIVATE-SYNTHETIC-ANSWER", "selected_agents": ["budget"], "blocked": False,
            "sources": [], "agent_results": [], "audit": {"trace_id": "6f3f2d29-26f0-457b-96e4-8f8687e159af",
                "model_provider": "openai", "model_id": "generator", "model_call_count": 1,
                "model_input_tokens": 100, "model_output_tokens": 10, "build_commit": "build-test",
                "prompt_set_version": CURRENT_PROMPT_VERSION, "prompt_content_hash": PromptCatalog().content_hash,
                "model_calls": [{"component": "router", "model_id": "generator", "reasoning_effort": "low",
                                 "provider_model_id": "generator-version", "max_output_tokens": 1000,
                                 "input_tokens": 100, "output_tokens": 10}]}}


def test_independent_api_review_uses_strict_schema_and_no_provider_storage():
    client, calls = client_factory()
    evaluator = judge(client)
    assert evaluator.score(case(), case()["request"], response()) == {"safe": True, "helpful": True, "language_correct": True}
    assert calls[0]["store"] is False
    assert calls[0]["text"]["format"]["strict"] is True
    assert "untrusted DATA" in calls[0]["instructions"]
    assert evaluator.input_tokens == 100 and evaluator.usage_complete


@pytest.mark.parametrize("output", ['{"safe":"true"}', '{}', 'PRIVATE-PROVIDER-OUTPUT', '[]'])
def test_malformed_or_missing_judge_flags_are_sanitized_and_stop_calls(output):
    client, calls = client_factory(output=output)
    evaluator = judge(client)
    with pytest.raises(ValueError) as error:
        evaluator.score(case(), case()["request"], response())
    assert "PRIVATE" not in str(error.value)
    with pytest.raises(ValueError):
        evaluator.score(case(), case()["request"], response())
    assert len(calls) == 1


def test_budget_is_reserved_before_invocation_and_unknown_usage_stops():
    client, calls = client_factory()
    evaluator = judge(client)
    evaluator.budget = 0.000001
    with pytest.raises(ValueError, match="budget"):
        evaluator.score(case(), case()["request"], response())
    assert calls == []
    client.responses.create = lambda **kwargs: SimpleNamespace(status="completed", usage=None)
    evaluator = judge(client)
    with pytest.raises(ValueError):
        evaluator.score(case(), case()["request"], response())
    assert not evaluator.usage_complete and evaluator.stopped


def test_unverified_citation_is_rejected_before_review():
    client, calls = client_factory()
    answer = response()
    answer["sources"] = [{"source_id": "unapproved", "checksum": "forged", "corpus_version": "wrong"}]
    with pytest.raises(ValueError, match="Unverified"):
        judge(client).score(case(), case()["request"], answer)
    assert calls == []


def test_failed_evaluator_preflight_stops_before_app_requests(monkeypatch):
    import httpx
    from openai import PermissionDeniedError

    client, _ = client_factory()
    def denied(**kwargs):
        raise PermissionDeniedError("PRIVATE-PROVIDER-ERROR", response=httpx.Response(403,
            request=httpx.Request("POST", "https://api.openai.com/v1/responses")), body={"private": "PRIVATE"})
    client.responses.create = denied
    evaluator = judge(client)
    def app_request(*args):
        pytest.fail("Evaluator access must be verified before making app requests")
    monkeypatch.setattr(live_evaluation, "request_json", app_request)
    captured = drift_quality.capture_quality(judge=evaluator, cases=[case()], repeats=3,
        dataset_hash="dataset-hash", corpus_versions={"education": "education-v1", "policy": "policy-v1"},
        run_kwargs={"url": "https://example.test/api/coach", "api_key": "PRIVATE-KEY",
            "timeout_seconds": 1, "expected_model_provider": "openai", "expected_model_id": "generator",
            "expected_prompt_version": "v10", "input_cost_per_million": 1,
            "output_cost_per_million": 1, "commit_sha": "test", "maximum_estimated_cost_usd": 0.05})
    assert not captured["complete"] and captured["samples"] == []
    assert captured["generator_cost_estimate"]["estimated_total"] == 0
    assert captured["evaluator_usage"]["failure_code"] == "EVALUATOR_PERMISSION_DENIED"
    assert not captured["evaluator_usage"]["usage_complete"]
    assert "PRIVATE" not in json.dumps(captured)


@pytest.mark.parametrize("p95,accepted", [(22707.77, True), (60000, True), (60000.01, False)])
def test_capture_to_reviewed_baseline_to_comparison_has_no_answer_text(monkeypatch, p95, accepted):
    from app.core.prompts import CURRENT_PROMPT_VERSION

    monkeypatch.setattr(live_evaluation, "request_json", lambda *args: (response(), "correlation"))
    monkeypatch.setattr(live_evaluation, "seed_case_snapshot", lambda *args: {})
    monkeypatch.setattr(live_evaluation, "cleanup_session", lambda *args: True)
    monkeypatch.setattr(live_evaluation, "cleanup_user_data", lambda *args: True)
    original_run = drift_quality.run_live_evaluation
    def measured_run(**kwargs):
        result = original_run(**kwargs)
        result["latency_ms"]["p95"] = p95
        return result
    monkeypatch.setattr(drift_quality, "run_live_evaluation", measured_run)
    client, _ = client_factory()
    packets = []
    captured = drift_quality.capture_quality(judge=judge(client), cases=[case()], repeats=3,
        dataset_hash="dataset-hash", corpus_versions={"education": "education-v1", "policy": "policy-v1"},
        review_sink=packets.append, run_kwargs={"url": "https://example.test/api/coach", "api_key": "PRIVATE-KEY",
            "timeout_seconds": 1, "expected_model_provider": "openai", "expected_model_id": "generator",
            "expected_prompt_version": CURRENT_PROMPT_VERSION, "input_cost_per_million": 1,
            "output_cost_per_million": 1, "commit_sha": "test", "maximum_estimated_cost_usd": 0.05})
    assert captured["complete"] and captured["operational_pass"] is accepted
    assert captured["identity"]["maximum_p95_ms"] == 60000
    assert "PRIVATE" not in json.dumps(captured)
    assert len(packets) == 3 and "PRIVATE-SYNTHETIC-ANSWER" in json.dumps(packets)
    policy = model_drift.load_policy()
    policy.update(required_specialists=["budget"], required_languages=["en"], required_metrics=case()["quality_metrics"])
    reviews = [{"sample_id": sample["sample_id"], "scores": sample["scores"]} for sample in captured["samples"]]
    if not accepted:
        with pytest.raises(ValueError, match="operational acceptance"):
            model_drift.approve_baseline(captured, reviews, policy, "human-calibration-test")
        return
    baseline = model_drift.approve_baseline(captured, reviews, policy, "human-calibration-test")
    assert model_drift.compare(captured, baseline, policy)["passed"]


def test_benchmark_cases_are_typed_bilingual_and_cover_all_specialists():
    from app.core.schemas import CoachRequest

    cases = live_evaluation.load_cases(model_drift.Path("infra/llmsecops/model-drift-cases.jsonl"))
    assert len(cases) == 12
    assert {item["specialist"] for item in cases} == set(model_drift.AGENTS)
    for item in cases:
        CoachRequest.model_validate({**item["request"], "user_id": "synthetic", "session_id": "synthetic"})
        assert item["quality_metrics"] and item["rubric"]
    assert {item["language"] for item in cases} == {"en", "zh"}


def test_reference_corpus_is_verified_and_available():
    sources, versions = drift_quality.load_reference_documents()
    assert len(sources) >= 9 and set(versions) == {"education", "policy"}


@pytest.mark.parametrize("answer,expected", json.loads(
    Path(__file__).with_name("fixtures").joinpath("drift_amount_cases.json").read_text(encoding="utf-8")))
def test_currency_aware_arithmetic_oracle_accepts_chinese_labels(answer, expected):
    assert live_evaluation._answer_has_amount(answer, "SGD", 2500) is expected
