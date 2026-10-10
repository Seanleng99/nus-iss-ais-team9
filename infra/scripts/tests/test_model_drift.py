from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from infra.scripts import model_drift as drift


def capture(count=100, failed=0, metric="helpful", instant=None):
    samples = [{"sample_id": f"case:{index}", "case_id": "case", "specialist": "budget",
                "language": "en", "intent": "calculation", "structural_pass": True,
                "scores": {"safe": True, "helpful": index >= failed}}
               for index in range(count)]
    if metric != "helpful":
        for index, sample in enumerate(samples):
            sample["scores"][metric] = index >= failed
            sample["scores"]["helpful"] = True
    result = {"schema_version": 1, "measurement": "live_quality_capture", "run_id": drift.uuid4().hex,
              "generated_at": (instant or datetime.now(UTC)).isoformat(),
              "identity": {"model_provider": "openai", "model_id": "generator", "build_commit": "build", "target_host": "example.test",
                  "prompt_set_version": "v10", "prompt_content_hash": "prompt-hash", "dataset_sha256": "dataset-hash",
                  "evaluator_model": "judge", "evaluator_response_model": "judge-version", "evaluator_prompt_sha256": "judge-prompt",
                  "evaluation_mode": "separate_model",
                  "evaluator_schema_sha256": "judge-schema", "evaluator_reasoning_effort": "low", "evaluator_max_output_tokens": 2048,
                  "generator_price_assumptions": [1, 1], "generator_budget_usd": 0.05, "maximum_p95_ms": 60000,
                  "corpus_versions": {"education": "education-version", "policy": "policy-version"},
                  "roles": {"router": {"model_id": "generator", "provider_model_id": "generator-version",
                                       "reasoning_effort": "low", "max_output_tokens": 1000}}},
              "expected_samples": [{"sample_id": item["sample_id"], "specialist": item["specialist"],
                  "language": item["language"], "intent": item["intent"], "metrics": sorted(item["scores"])} for item in samples],
              "samples": samples, "complete": True, "operational_pass": True, "latency_ms": {"p95": 22707.77}}
    return seal(result)


def seal(result):
    result["evidence_sha256"] = drift.digest({k: v for k, v in result.items() if k != "evidence_sha256"})
    return result


@pytest.fixture
def policy():
    policy = drift.load_policy()
    policy["evaluation_mode"] = "separate_model"
    policy.update(required_specialists=["budget"], required_languages=["en"], required_metrics=["safe", "helpful"])
    return policy


def baseline(captured, policy):
    reviews = [{"sample_id": item["sample_id"], "scores": item["scores"]} for item in captured["samples"]]
    return drift.approve_baseline(captured, reviews, policy, "human-review-20261010")


def test_matching_live_quality_passes_without_replacing_baseline(policy):
    reference = baseline(capture(), policy)
    original = deepcopy(reference)
    assert drift.compare(capture(), reference, policy)["status"] == "pass"
    assert reference == original


@pytest.mark.parametrize("mutation", ["private_field", "unknown_stage", "unknown_usage", "count_mismatch",
                                     "error_content", "codes_content", "codes_overflow", "codes_type"])
def test_execution_diagnostics_reject_content_or_contradictory_acceptance(mutation):
    current = capture(count=1)
    current["samples"][0]["sample_id"] = current["expected_samples"][0]["sample_id"] = "case:1"
    record = {"case_id": "case", "repeat": 1, "passed": True, "cleanup_succeeded": True,
              "token_usage_complete": True, "input_tokens": 10, "output_tokens": 5, "model_call_count": 1,
              "usage_failure_codes": [], "failed_checks": [], "trace_id": None, "correlation_id": None,
              "error_code": "INVALID_STRUCTURED_RESPONSE", "error_codes": ["AI_SERVICE_UNAVAILABLE"]}
    current["generator_execution"] = {"requested_runs": 1, "attempted_runs": 1,
        "completed_requested_runs": True, "usage_unknown": False, "fixture_stopped": False, "records": [record]}
    drift.validate_capture(seal(current))
    if mutation == "private_field":
        record["answer"] = "PRIVATE-CONTENT"
    elif mutation == "unknown_stage":
        record["failure_stage"] = "PRIVATE-CONTENT"
    elif mutation == "unknown_usage":
        current["generator_execution"]["usage_unknown"] = True
    elif mutation == "error_content":
        record["error_code"] = "PRIVATE-CONTENT"
    elif mutation == "codes_content":
        record["error_codes"] = ["PRIVATE message"]
    elif mutation == "codes_overflow":
        record["error_codes"] = ["CODE"] * 21
    elif mutation == "codes_type":
        record["error_codes"] = "CODE"
    else:
        current["generator_execution"]["attempted_runs"] = 0
    with pytest.raises(ValueError):
        drift.validate_capture(seal(current))


def test_relative_drop_requires_two_distinct_runs(policy):
    instant = datetime.now(UTC) - timedelta(minutes=2)
    reference = baseline(capture(instant=instant - timedelta(minutes=1)), policy)
    first_capture = capture(failed=6, instant=instant)
    first = drift.compare(first_capture, reference, policy)
    assert first["status"] == "warning" and first["passed"]
    repeated = drift.compare(first_capture, reference, policy, first)
    assert repeated["status"] == "warning"
    second = drift.compare(capture(failed=6), reference, policy, first)
    assert second["status"] == "drift" and not second["passed"]


@pytest.mark.parametrize("mutation", ["stale", "identity", "baseline", "interrupted"])
def test_stale_or_ineligible_history_cannot_confirm_drift(policy, mutation):
    reference = baseline(capture(), policy)
    previous = drift.compare(capture(failed=6, instant=datetime.now(UTC) - timedelta(minutes=2)), reference, policy)
    if mutation == "stale":
        previous["generated_at"] = (datetime.now(UTC) - timedelta(days=15)).isoformat()
    elif mutation == "identity":
        previous["identity_sha256"] = "other"
    elif mutation == "baseline":
        previous["baseline_id"] = "other"
    else:
        previous["status"] = "incomplete"
    assert drift.compare(capture(failed=6), reference, policy, previous)["status"] == "warning"


def test_first_unsafe_sample_fails_even_with_low_counts_and_changed_config(policy):
    current = capture(count=1, failed=1, metric="safe")
    reference = baseline(capture(), policy)
    current["identity"]["model_id"] = "changed"
    seal(current)
    result = drift.compare(current, reference, policy)
    assert result["status"] == "critical" and not result["passed"]


def test_absolute_quality_failure_does_not_wait_for_confirmation(policy):
    assert drift.compare(capture(failed=20), baseline(capture(), policy), policy)["status"] == "acceptance_failed"


@pytest.mark.parametrize("mutation", ["missing", "unscored", "boolean", "duplicate", "checksum", "fixture", "text"])
def test_missing_or_invalid_evidence_never_passes(policy, mutation):
    current = capture()
    if mutation == "missing":
        current["samples"].pop()
    elif mutation == "unscored":
        current["samples"][0]["scores"] = None
    elif mutation == "boolean":
        current["samples"][0]["scores"]["safe"] = "true"
    elif mutation == "duplicate":
        current["samples"].append(current["samples"][0])
    elif mutation == "fixture":
        current["identity"]["model_provider"] = "local_fixture"
    elif mutation == "text":
        current["samples"][0]["answer"] = "PRIVATE ANSWER"
    seal(current)
    if mutation == "checksum":
        current["samples"][0]["scores"]["helpful"] = False
    if mutation in {"missing", "unscored"}:
        assert drift.compare(current, baseline(capture(), policy), policy)["status"] == "incomplete"
    else:
        with pytest.raises(ValueError):
            drift.compare(current, baseline(capture(), policy), policy)


def test_changed_policy_or_runtime_requires_new_acceptance_baseline(policy):
    reference = baseline(capture(), policy)
    current = capture()
    current["identity"]["prompt_content_hash"] = "new"
    seal(current)
    assert drift.compare(current, reference, policy)["status"] == "configuration_changed"
    altered = deepcopy(policy)
    altered["metrics"]["helpful"]["allowed_drop"] = 0.1
    assert drift.compare(capture(), reference, altered)["status"] == "configuration_changed"


def test_latency_policy_change_requires_fresh_acceptance(policy):
    reference = baseline(capture(), policy)
    changed = deepcopy(policy)
    changed["operational"]["maximum_p95_ms"] = 70000
    current = capture()
    current["identity"]["maximum_p95_ms"] = 70000
    seal(current)
    assert drift.compare(current, reference, changed)["status"] == "configuration_changed"
    with pytest.raises(ValueError, match="latency limit"):
        baseline(capture(), changed)


def test_excess_latency_cannot_be_marked_as_operationally_accepted(policy):
    current = capture()
    current["latency_ms"]["p95"] = 60000.01
    seal(current)
    with pytest.raises(ValueError, match="contradicts"):
        baseline(current, policy)


def test_same_model_evaluation_is_explicit_and_needs_matching_policy_and_models(policy):
    current = capture()
    current["identity"].update(evaluation_mode="same_model", evaluator_model="generator",
                               evaluator_response_model="generator-version")
    seal(current)
    same_policy = deepcopy(policy)
    same_policy["evaluation_mode"] = "same_model"
    reference = baseline(current, same_policy)
    assert drift.compare(current, reference, same_policy)["passed"]
    with pytest.raises(ValueError, match="evaluator mode"):
        baseline(current, policy)
    current["identity"]["roles"]["router"]["provider_model_id"] = "other-model"
    seal(current)
    with pytest.raises(ValueError, match="matching generator"):
        drift.validate_capture(current)


def test_baseline_requires_complete_matching_human_reviews(policy):
    current = capture()
    with pytest.raises(ValueError):
        drift.approve_baseline(current, [], policy, "review")
    reviews = [{"sample_id": item["sample_id"], "scores": {**item["scores"], "safe": False}} for item in current["samples"]]
    with pytest.raises(ValueError):
        drift.approve_baseline(current, reviews, policy, "review")


def test_shipped_policy_rejects_a_benchmark_missing_required_specialists_or_metrics():
    current = capture()
    reviews = [{"sample_id": sample["sample_id"], "scores": sample["scores"]} for sample in current["samples"]]
    shipped = drift.load_policy()
    shipped["evaluation_mode"] = "separate_model"
    with pytest.raises(ValueError, match="subgroup"):
        drift.approve_baseline(current, reviews, shipped, "review")


def test_live_queries_reject_inadequate_retention(policy):
    client = SimpleNamespace(describe_log_groups=lambda **kwargs: {"logGroups": [
        {"logGroupName": "/ecs/demo/ai", "retentionInDays": 14}]})
    with pytest.raises(ValueError, match="retention"):
        drift.collect_inputs(client, "/ecs/demo/ai", policy["inputs"])


def inputs(count=100, current_language="en"):
    end = datetime(2026, 10, 10, tzinfo=UTC)
    start = end - timedelta(days=7)
    def window(begin, finish, language):
        return {"start": begin.isoformat(), "end": finish.isoformat(), "environment": "/ecs/demo/ai",
                "counts": {"input_language": {language: count}, "input_length_band": {"short": count},
                           "intent_bucket": {"analysis": count}, "agent_mix": {"budget": count},
                           "needs_input": {"false": count}, "blocked": {"false": count}}}
    return {"schema_version": 1, "measurement": "input_aggregates",
            "reference": window(start - timedelta(days=21), start, "en"), "current": window(start, end, current_language)}


def test_input_distribution_change_is_measured_and_small_samples_are_ineligible(policy):
    measured = drift.input_checks(inputs(current_language="zh"), policy["inputs"])
    assert measured["inputs/input_language"]["relative_breach"]
    assert not measured["inputs/agent_mix"]["relative_breach"]
    small = drift.input_checks(inputs(count=4), policy["inputs"])
    assert all(not item["eligible"] and item["js_divergence"] is None for item in small.values())


def test_overlapping_windows_and_arbitrary_input_buckets_are_rejected(policy):
    current = inputs()
    current["reference"]["end"] = current["current"]["end"]
    with pytest.raises(ValueError):
        drift.input_checks(current, policy["inputs"])
    current = inputs()
    current["current"]["counts"]["input_language"] = {"private-question": 100}
    with pytest.raises(ValueError):
        drift.input_checks(current, policy["inputs"])


def test_rare_cells_do_not_appear_in_retained_report(policy):
    current = inputs()
    current["current"]["counts"]["input_language"] = {"en": 99, "zh": 1}
    result = drift.input_checks(current, policy["inputs"])
    assert "zh" not in drift.json.dumps(result)


def test_sns_notification_contains_only_allowlisted_metadata(policy):
    published = []
    client = SimpleNamespace(publish=lambda **kwargs: published.append(kwargs))
    report = drift.compare(capture(failed=1, metric="safe"), baseline(capture(), policy), policy)
    report["answer"] = "PRIVATE-ANSWER"
    assert drift.notify(report, client, "arn:aws:sns:ap-southeast-1:123456789012:demo")
    assert "PRIVATE-ANSWER" not in str(published)
    assert "P1" in published[0]["Message"]
    report["status"] = "warning"
    assert not drift.notify(report, client, "unused")


def test_cloudwatch_queries_only_aggregates_and_includes_config_pin(policy):
    queries = []
    client = SimpleNamespace(
        describe_log_groups=lambda **kwargs: {"logGroups": [{"logGroupName": "/ecs/demo/ai", "retentionInDays": 30}]},
        start_query=lambda **kwargs: queries.append(kwargs) or {"queryId": "q"},
        get_query_results=lambda **kwargs: {"status": "Complete", "results": []},
        stop_query=lambda **kwargs: {},
    )
    result = drift.collect_inputs(client, "/ecs/demo/ai", policy["inputs"], identity={"model_id": "model", "prompt_content_hash": "hash", "build_commit": "build"})
    assert all('stats count(*)' in query["queryString"] and 'prompt_content_hash = "hash"' in query["queryString"] for query in queries)
    assert result["reference"]["end"] == result["current"]["start"]
    assert "@message" not in str(queries)
