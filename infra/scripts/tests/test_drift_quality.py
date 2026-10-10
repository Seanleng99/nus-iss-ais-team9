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


def client_factory(output=None, model="judge-version", **overrides):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        required = json.loads(kwargs["input"])["required_metrics"]
        scores = {metric: True if metric in required else None for metric in model_drift.METRICS}
        return SimpleNamespace(status="completed", usage=SimpleNamespace(input_tokens=100, output_tokens=10),
                               model=model, output_text=json.dumps(scores) if output is None else output,
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
    schema = calls[0]["text"]["format"]["schema"]
    assert schema["properties"]["safe"] == {"type": "boolean"}
    assert schema["properties"]["financial_correct"] == {"type": "null"}
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
@pytest.mark.parametrize("evaluation_mode", ["separate_model", "same_model"])
@pytest.mark.parametrize("repeats", [1, 2, 3])
def test_capture_to_reviewed_baseline_to_comparison_has_no_answer_text(monkeypatch, p95, accepted, evaluation_mode, repeats):
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
    client, _ = client_factory(model="generator-version" if evaluation_mode == "same_model" else "judge-version")
    evaluator = judge(client)
    if evaluation_mode == "same_model":
        evaluator.model = "generator"
    packets = []
    captured = drift_quality.capture_quality(judge=evaluator, cases=[case()], repeats=repeats, evaluation_mode=evaluation_mode,
        dataset_hash="dataset-hash", corpus_versions={"education": "education-v1", "policy": "policy-v1"},
        review_sink=packets.append, run_kwargs={"url": "https://example.test/api/coach", "api_key": "PRIVATE-KEY",
            "timeout_seconds": 1, "expected_model_provider": "openai", "expected_model_id": "generator",
            "expected_prompt_version": CURRENT_PROMPT_VERSION, "input_cost_per_million": 1,
            "output_cost_per_million": 1, "commit_sha": "test", "maximum_estimated_cost_usd": 0.05})
    assert captured["complete"] and captured["operational_pass"] is accepted
    assert captured["identity"]["maximum_p95_ms"] == 60000
    assert "PRIVATE" not in json.dumps(captured)
    assert len(packets) == repeats and "PRIVATE-SYNTHETIC-ANSWER" in json.dumps(packets)
    execution = captured["generator_execution"]
    assert execution["attempted_runs"] == repeats and not execution["usage_unknown"]
    assert all(record["token_usage_complete"] and record["failed_checks"] == []
               for record in execution["records"])
    policy = model_drift.load_policy()
    policy["evaluation_mode"] = evaluation_mode
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


@pytest.mark.parametrize("problem,diagnostic", [
    ("build", "QUALITY_DEPLOYED_BUILD_CHANGED"),
    ("role", "QUALITY_ROLE_POLICY_CHANGED"),
    ("identity", "QUALITY_GENERATOR_IDENTITY_MISMATCH"),
])
def test_remote_identity_change_stops_with_specific_content_free_diagnostic(monkeypatch, problem, diagnostic):
    from app.core.prompts import CURRENT_PROMPT_VERSION

    first, second = response(), response()
    if problem == "build":
        second["audit"]["build_commit"] = "new-build"
    elif problem == "role":
        second["audit"]["model_calls"][0]["max_output_tokens"] = 2000
    else:
        second["audit"]["prompt_content_hash"] = "different-prompt"
    answers = iter([first, second])
    monkeypatch.setattr(live_evaluation, "request_json", lambda *args: (next(answers), "correlation"))
    monkeypatch.setattr(live_evaluation, "seed_case_snapshot", lambda *args: {})
    monkeypatch.setattr(live_evaluation, "cleanup_session", lambda *args: True)
    monkeypatch.setattr(live_evaluation, "cleanup_user_data", lambda *args: True)
    client, calls = client_factory()
    captured = drift_quality.capture_quality(judge=judge(client), cases=[case()], repeats=3,
        dataset_hash="dataset-hash", corpus_versions={"education": "education-v1", "policy": "policy-v1"},
        run_kwargs={"url": "https://example.test/api/coach", "api_key": "PRIVATE-KEY", "timeout_seconds": 1,
            "expected_model_provider": "openai", "expected_model_id": "generator",
            "expected_prompt_version": CURRENT_PROMPT_VERSION,
            "input_cost_per_million": 1, "output_cost_per_million": 1, "commit_sha": "test",
            "maximum_estimated_cost_usd": 0.05})
    assert not captured["complete"] and len(captured["samples"]) == 2
    assert captured["samples"][-1]["error_code"] == diagnostic
    assert captured["samples"][-1]["scores"] is None
    assert not captured["generator_execution"]["usage_unknown"]
    assert len(calls) == 2  # Preflight plus the first sample; no judge call for mixed identity.
    assert "PRIVATE" not in json.dumps(captured)


def test_fixture_failure_is_retained_without_claiming_unknown_generation_spend(monkeypatch):
    client, _ = client_factory()
    def fail_seed(*args):
        raise live_evaluation.LiveEndpointError(503, "PRIVATE-ERROR-CONTENT")
    monkeypatch.setattr(live_evaluation, "seed_case_snapshot", fail_seed)
    monkeypatch.setattr(live_evaluation, "request_json", lambda *args: pytest.fail("No model request after failed seeding"))
    monkeypatch.setattr(live_evaluation, "cleanup_session", lambda *args: True)
    monkeypatch.setattr(live_evaluation, "cleanup_user_data", lambda *args: True)
    captured = drift_quality.capture_quality(judge=judge(client), cases=[case()], repeats=3,
        dataset_hash="dataset-hash", corpus_versions={"education": "education-v1", "policy": "policy-v1"},
        run_kwargs={"url": "https://example.test/api/coach", "api_key": "PRIVATE-KEY", "timeout_seconds": 1,
            "expected_model_provider": "openai", "expected_model_id": "generator", "expected_prompt_version": "v10",
            "input_cost_per_million": 1, "output_cost_per_million": 1, "commit_sha": "test",
            "maximum_estimated_cost_usd": 0.05})
    execution = captured["generator_execution"]
    assert not captured["complete"] and not captured["operational_pass"]
    assert execution["fixture_stopped"] and not execution["usage_unknown"]
    assert execution["attempted_runs"] == 1
    record = execution["records"][0]
    assert record["http_status"] == 503 and record["failure_stage"] == "fixture_setup"
    assert record["token_usage_complete"] and record["input_tokens"] == record["output_tokens"] == 0
    assert record["correlation_id"] is None and "PRIVATE" not in json.dumps(captured)
    assert "live evaluation fixture setup failed" in captured["operational_failures"]
    assert "live evaluation could not account for model usage" not in captured["operational_failures"]


def test_execution_metadata_preserves_bounded_recovered_codes_without_error_content():
    record = {"case_id": "synthetic", "repeat": 1, "passed": False, "cleanup_succeeded": True,
        "token_usage_complete": True, "input_tokens": 100, "output_tokens": 50, "model_call_count": 2,
        "checks": [], "error_code": "INVALID_STRUCTURED_RESPONSE",
        "error_codes": ["AI_SERVICE_UNAVAILABLE", "INVALID_STRUCTURED_RESPONSE",
                        "PRIVATE financial message", "INVALID_STRUCTURED_RESPONSE"],
        "error": "PRIVATE error details"}
    retained = drift_quality._execution_metadata(record)
    assert retained["error_code"] == "INVALID_STRUCTURED_RESPONSE"
    assert retained["error_codes"] == ["AI_SERVICE_UNAVAILABLE", "INVALID_STRUCTURED_RESPONSE"]
    assert "PRIVATE" not in json.dumps(retained)
    record["error_code"] = "PRIVATE message"
    record["error_codes"] = ["CODE_" + str(index) for index in range(21)]
    retained = drift_quality._execution_metadata(record)
    assert "error_code" not in retained and len(retained["error_codes"]) == 20


@pytest.mark.parametrize("problem", ["missing_call_tokens", "count_mismatch", "total_mismatch"])
def test_cost_budget_requires_consistent_per_call_usage_and_retains_reason(monkeypatch, problem):
    answer = response()
    audit = answer["audit"]
    if problem == "missing_call_tokens":
        audit["model_calls"][0].pop("input_tokens")
    elif problem == "count_mismatch":
        audit["model_call_count"] = 2
    else:
        audit["model_input_tokens"] = 101
    monkeypatch.setattr(live_evaluation, "request_json", lambda *args: (answer, "correlation"))
    monkeypatch.setattr(live_evaluation, "seed_case_snapshot", lambda *args: {})
    monkeypatch.setattr(live_evaluation, "cleanup_session", lambda *args: True)
    monkeypatch.setattr(live_evaluation, "cleanup_user_data", lambda *args: True)
    client, _ = client_factory()
    captured = drift_quality.capture_quality(judge=judge(client), cases=[case()], repeats=3,
        dataset_hash="dataset-hash", corpus_versions={"education": "education-v1", "policy": "policy-v1"},
        run_kwargs={"url": "https://example.test/api/coach", "api_key": "PRIVATE-KEY", "timeout_seconds": 1,
            "expected_model_provider": "openai", "expected_model_id": "generator", "expected_prompt_version": "v10",
            "input_cost_per_million": 1, "output_cost_per_million": 1, "commit_sha": "test",
            "maximum_estimated_cost_usd": 0.05})
    execution = captured["generator_execution"]
    assert not captured["complete"] and execution["usage_unknown"]
    assert not execution["fixture_stopped"] and execution["attempted_runs"] == 1
    assert "MODEL_USAGE_INCONSISTENT" in execution["records"][0]["usage_failure_codes"]
    if problem == "missing_call_tokens":
        assert "MODEL_CALL_USAGE_MISSING" in execution["records"][0]["usage_failure_codes"]
    assert "PRIVATE" not in json.dumps(captured)


@pytest.mark.parametrize("answer,expected", json.loads(
    Path(__file__).with_name("fixtures").joinpath("drift_amount_cases.json").read_text(encoding="utf-8")))
def test_currency_aware_arithmetic_oracle_accepts_chinese_labels(answer, expected):
    assert live_evaluation._answer_has_amount(answer, "SGD", 2500) is expected
