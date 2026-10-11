"""Offline contracts for release live checks: no credentials or provider calls."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from infra.scripts import agent_live_evaluation as live
from infra.scripts import live_evaluation as runner
from infra.scripts import summarize_agent_evaluations as combined

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def no_summary_pollution(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def workflow():
    return yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)


def test_ci_has_seven_offline_suites_and_release_owns_paid_live_checks():
    config = workflow()
    assert not config["on"]["workflow_dispatch"]
    assert set(config["jobs"]["offline"]["strategy"]["matrix"]["suite"]) == set(live.SUITES)
    assert "live" not in config["jobs"] and "security-live" not in config["jobs"]
    assert "environment" not in config["jobs"]["offline"]
    assert set(config["jobs"]["offline"]["env"].values()) == {"local_fixture", "${{ matrix.suite }}"}
    assert config["jobs"]["report"]["continue-on-error"] == "true"
    assert config["jobs"]["agent-test-gate"]["needs"] == ["changes", "offline", "metrics", "ai-service"]
    release = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    assert release["jobs"]["deploy-demo"]["environment"]["name"] == "demo"
    ci = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    assert "agent-evaluations" not in ci["jobs"]
    assert "secrets" not in ci["jobs"]["offline"]
    assert set(ci["jobs"]["agent-test-gate"]["needs"]) == {"changes", "offline", "metrics", "ai-service"}
    assert "live" not in ci["jobs"]["agent-test-gate"]["env"]


def test_legacy_duplicate_test_entrypoints_are_removed():
    for name in ("spending-agent-tests", "budget-agent-tests", "goal-agent-tests", "investment-agent-tests",
                 "risk-compliance-agent-tests", "agent-test-suite", "investment-agent-live", "budget-live-acceptance"):
        assert not (ROOT / f".github/workflows/{name}.yml").exists()


@pytest.mark.parametrize("suite", live.SUITES)
def test_every_live_definition_includes_questions_expected_metrics_and_criteria(suite):
    report = live.initial_report(suite)
    spec = report["specification"]
    assert spec["expected_outputs"] and spec["metrics"] and spec["acceptance_criteria"]
    assert spec["limits"]["repeats"] == 1 and spec["limits"]["generation_retries"] == 0
    assert len(list(live.questions(report))) == (3 if suite == "rag" else spec["planned_turns"])
    assert report["status"] == "NOT RUN"
    assert all(len(value) == 64 for value in report["dataset_hashes"].values())


def sample_response():
    return {"answer": "Recorded food total is SGD 120.", "blocked": False, "selected_agents": ["spending"],
            "agent_results": [{"agent": "spending", "data": {"category_totals": {"food": 120}}}],
            "audit": {"build_commit": "a"*40, "model_provider": "openai", "model_id": "gpt-6-luna",
                      "prompt_set_version": "v10", "model_call_count": 1, "model_input_tokens": 15,
                      "model_output_tokens": 20, "answer_status": "answered",
                      "model_calls": [{"component": "agent_spending", "model_id": "gpt-6-luna",
                                       "status": "completed", "error_code": None, "output_characters": 100,
                                       "input_tokens": 15, "output_tokens": 20}]}}


@pytest.mark.parametrize("fault", [None, "wrong_role", "failed", "fixture", "empty", "missing_usage"])
def test_real_specialist_proof_cannot_be_replaced_by_any_model_call(fault):
    response = sample_response()
    call = response["audit"]["model_calls"][0]
    if fault == "wrong_role": call["component"] = "router"
    elif fault == "failed": call["status"] = "failed"
    elif fault == "fixture": call["model_id"] = "local_fixture"
    elif fault == "empty": call["output_characters"] = 0
    elif fault == "missing_usage": call.pop("input_tokens")
    passed, _ = runner.evaluate_response(response, {"required_model_components": ["agent_spending"],
        "agent_data": {"spending": {"category_totals": {"food": 120}}}},
        expected_model_provider="openai", expected_model_id="gpt-6-luna", expected_prompt_version="v10")
    assert passed is (fault is None)


def test_wrong_arithmetic_and_failed_build_or_usage_are_rejected():
    response = sample_response()
    passed, _ = runner.evaluate_response(response, {"agent_data": {"spending": {"category_totals": {"food": 999}}}},
        expected_model_provider="openai", expected_model_id="gpt-6-luna", expected_prompt_version="v10")
    assert not passed
    assert all(row["passed"] for row in live.response_checks("a"*40)(response, {}))
    assert not all(row["passed"] for row in live.response_checks("b"*40)(response, {}))
    response["audit"]["model_input_tokens"] = 0
    assert not all(row["passed"] for row in live.response_checks("a"*40)(response, {}))


@pytest.mark.parametrize("requested,result", [(False, "skipped"), (True, "failure"), (True, "success")])
def test_missing_live_artifact_cannot_be_presented_as_pass(tmp_path, requested, result):
    rows = combined.collect(tmp_path, live_requested=requested, live_job_result=result)
    assert len(rows) == 16
    assert all(row["status"] != "PASS" for row in rows)
    live_rows = [row for row in rows if row["mode"] == "live"]
    assert all(row["status"].startswith("NOT RUN" if requested else "SKIPPED") for row in live_rows)


def test_pre_deployment_report_marks_all_live_suites_optional_and_off_by_default(tmp_path):
    rows = combined.collect(tmp_path, live_requested=False, live_job_result="not_run", phase="pre_deployment")
    live_rows = [row for row in rows if row["mode"] == "live"]
    assert len(live_rows) == 7
    assert all(row["status"] == "OPTIONAL — selected in Release to AWS; off by default" for row in live_rows)
    assert "Enabled stages require passing evidence" in combined.render(rows)
    assert "Enabled stages require passing evidence" in combined.render_html(rows)


def test_failed_live_artifact_survives_advisory_success(tmp_path):
    directory = tmp_path / "agent-live-budget"
    report = live.initial_report("budget")
    report["status"] = "FAIL"
    live.write_report(report, directory)
    rows = combined.collect(tmp_path, live_requested=True, live_job_result="success")
    assert next(r for r in rows if r["suite"] == "budget" and r["mode"] == "live")["status"] == "FAIL"
    assert "FAIL" in combined.render(rows)


def test_report_escapes_model_html_and_keeps_full_answer(tmp_path):
    report = live.initial_report("spending")
    answer = "<script>alert('synthetic')</script>" + "x"*1000
    report.update(status="FAIL", records=[{"case_id": "spending-category-totals", "turns": [
        {"passed": False, "answer": answer}]}])
    live.write_report(report, tmp_path)
    assert answer == json.loads((tmp_path / "report.json").read_text())["records"][0]["turns"][0]["answer"]
    assert "<script>" not in (tmp_path / "index.html").read_text()
    assert "<script>" not in (tmp_path / "summary.md").read_text()


def run_stubbed(monkeypatch, *, capture=False, budget=1000):
    response = sample_response()
    monkeypatch.setattr(runner, "request_json", lambda *a: (deepcopy(response), "synthetic"))
    monkeypatch.setattr(runner, "seed_case_snapshot", lambda *a, **kw: {"transactions": 0, "goals": 0})
    monkeypatch.setattr(runner, "cleanup_session", lambda *a: True)
    monkeypatch.setattr(runner, "cleanup_user_data", lambda *a: True)
    cases = [{"id": str(i), "category": "spending", "request": {"message": "Synthetic question?"},
              "expected": {"blocked": False}} for i in range(2)]
    return runner.run_live_evaluation(url="https://example.test/api/coach", api_key="secret-never-log",
        cases=cases, repeats=1, timeout_seconds=1, expected_model_provider="openai", expected_model_id="gpt-6-luna",
        expected_prompt_version="v10", input_cost_per_million=0, output_cost_per_million=0, commit_sha="a"*40,
        capture_synthetic_dialogue=capture, maximum_total_tokens=budget,
        response_checks=live.response_checks("a"*40))


def test_synthetic_capture_is_explicit_default_preserves_metadata_only(monkeypatch):
    private = run_stubbed(monkeypatch)
    assert "answer" not in private["records"][0]["turns"][0]
    report = run_stubbed(monkeypatch, capture=True)
    turn = report["records"][0]["turns"][0]
    assert turn["question"] == "Synthetic question?"
    assert turn["answer"] == sample_response()["answer"]
    assert turn["expected"] == {"blocked": False}
    assert turn["checks"] and turn["model_calls"]
    assert "secret-never-log" not in json.dumps(report)


def test_token_budget_stops_before_next_call_and_incomplete_cannot_pass(monkeypatch):
    report = run_stubbed(monkeypatch, budget=1)
    assert report["total_runs"] == 1
    assert report["spending_stopped"] is True
    assert report["completed_requested_runs"] is False
    assert report["token_usage"]["total"] == 35


def test_live_routing_metrics_keep_missing_responses_in_denominator():
    cases = [{"id": "a", "expected": {"selected_agents": ["spending"]}},
             {"id": "b", "expected": {"selected_agents": ["budget"]}}]
    result = live.routing_metrics(cases, [{"case_id": "a", "turns": [
        {"selected_agents": ["spending", "investment_education"]}]}])
    assert result["routing_accuracy"] == 0
    assert result["routing_tp"] == result["routing_fp"] == result["routing_fn"] == 1
    assert result["routing_precision"] == result["routing_recall"] == result["routing_f1"] == .5


def test_unknown_usage_stops_generation_even_without_currency_pricing(monkeypatch):
    original = sample_response
    def missing():
        response = original()
        response["audit"]["model_calls"][0].pop("input_tokens")
        return response
    monkeypatch.setattr(__import__(__name__, fromlist=["sample_response"]), "sample_response", missing)
    report = run_stubbed(monkeypatch)
    assert report["usage_unknown"]
    assert report["spending_stopped"]
    assert report["total_runs"] == 1


@pytest.mark.parametrize("event,ref,attempt", [("push", "refs/heads/main", "1"),
    ("workflow_dispatch", "refs/heads/feature", "1"), ("workflow_dispatch", "refs/heads/main", "2")])
def test_live_cli_cannot_bypass_manual_main_first_attempt_gate(tmp_path, monkeypatch, event, ref, attempt):
    template = live.initial_report("budget")
    planned_questions = list(live.questions(template))
    monkeypatch.setattr(live, "questions", lambda report: iter(planned_questions))
    monkeypatch.setattr(live, "ROOT", tmp_path)
    monkeypatch.setattr(live, "initial_report", lambda suite: deepcopy(template))
    monkeypatch.setattr(live, "execute", lambda *a: pytest.fail("Provider execution must not start"))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", attempt)
    assert live.main(["--suite", "budget"]) == 1
    report = json.loads((tmp_path / "artifacts/agent-live/budget/report.json").read_text())
    assert report["status"] == "FAIL" and report["error_code"]


@pytest.mark.parametrize("source_event", ["push", "workflow_dispatch"])
@pytest.mark.parametrize("fault", [None, "wrong-source-event", "wrong-sha", "rerun"])
def test_post_deployment_cli_only_executes_fresh_successful_main_release(tmp_path, monkeypatch, source_event, fault):
    import boto3

    monkeypatch.setenv("RELEASE_SHA", "a" * 40)
    template = live.initial_report("budget")
    planned_questions = list(live.questions(template))
    monkeypatch.setattr(live, "questions", lambda report: iter(planned_questions))
    monkeypatch.setattr(live, "ROOT", tmp_path)
    monkeypatch.setattr(live, "initial_report", lambda suite: deepcopy(template))
    for key, value in {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REF": "refs/heads/main",
                       "GITHUB_RUN_ATTEMPT": "1", "RELEASE_SOURCE_EVENT": source_event,
                       "RELEASE_SOURCE_CONCLUSION": "success", "AWS_REGION": "test-region"}.items():
        monkeypatch.setenv(key, value)
    if fault == "wrong-source-event": monkeypatch.setenv("RELEASE_SOURCE_EVENT", "pull_request")
    elif fault == "wrong-sha": monkeypatch.setenv("RELEASE_SHA", "invalid")
    elif fault == "rerun": monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    calls = []
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: object())

    def executed(report, *args):
        calls.append(report["test_commit"])
        report["status"] = "PASS"

    monkeypatch.setattr(live, "execute", executed)
    assert live.main(["--suite", "budget", "--post-deployment"]) == (0 if fault is None else 1)
    assert calls == (["a" * 40] if fault is None else [])


def test_combined_html_retains_full_synthetic_answers_and_escapes_markup(tmp_path):
    report = live.initial_report("spending")
    answer = "<script>bad</script>" + "a"*700
    report.update(status="FAIL", records=[{"case_id": "spending-category-totals", "turns": [
        {"passed": False, "answer": answer}]}])
    live.write_report(report, tmp_path / "agent-live-spending")
    page = combined.render_html(combined.collect(tmp_path, live_requested=True, live_job_result="success"))
    assert "<script>bad</script>" not in page
    assert "&lt;script&gt;bad&lt;/script&gt;" in page
    assert "a"*700 in page
    assert "Expected output" in page and "Actual model answer" in page
