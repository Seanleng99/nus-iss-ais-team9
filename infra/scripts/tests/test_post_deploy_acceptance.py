"""Exercise the required release gate using synthetic reports, never paid calls."""
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
from itertools import product
from pathlib import Path

import pytest
import yaml

from infra.scripts import post_deploy_acceptance as acceptance

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40
ALL_LIVE = dict.fromkeys(acceptance.LIVE_FLAGS, True)


def context():
    return {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ATTEMPT": "1",
            "RELEASE_SOURCE_EVENT": "push", "RELEASE_SOURCE_CONCLUSION": "success", "RELEASE_SHA": SHA,
            "SMOKE_BACKEND_API_KEY": "synthetic-key", "COACH_SMOKE_URL": "https://example.test/api/coach",
            "SECURITY_TEST_ROLE": "synthetic-role", "INVESTMENT_TEST_OPENAI_SECRET_ID": "synthetic-secret-id",
            "LIVE_MODEL_INPUT_USD_PER_MILLION": "1", "LIVE_MODEL_OUTPUT_USD_PER_MILLION": "1",
            "FAIRNESS_LIVE_MAX_COST_USD": "1", "RELEASE_LIVE_SELECTION": json.dumps(ALL_LIVE),
            **dict.fromkeys(acceptance.LIVE_FLAGS.values(), "true")}


@pytest.mark.parametrize("source_event", ["push", "workflow_dispatch"])
def test_push_and_manual_ci_allow_release_preflight(source_event):
    assert acceptance.validate_config({**context(), "RELEASE_SOURCE_EVENT": source_event}) == ALL_LIVE


@pytest.mark.parametrize("source_event", ["push", "workflow_dispatch"])
@pytest.mark.parametrize("key,value", [
    ("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/feature"), ("GITHUB_RUN_ATTEMPT", "2"),
    ("RELEASE_SOURCE_EVENT", "pull_request"), ("RELEASE_SOURCE_EVENT", "schedule"),
    ("RELEASE_SOURCE_EVENT", ""), ("RELEASE_SOURCE_CONCLUSION", "failure"), ("RELEASE_SHA", ""),
    ("SMOKE_BACKEND_API_KEY", ""), ("SECURITY_TEST_ROLE", ""), ("LIVE_MODEL_INPUT_USD_PER_MILLION", ""),
    ("LIVE_MODEL_INPUT_USD_PER_MILLION", "nan"), ("LIVE_MODEL_OUTPUT_USD_PER_MILLION", "inf"),
    ("FAIRNESS_LIVE_MAX_COST_USD", "0"), ("FAIRNESS_LIVE_MAX_COST_USD", "-1"),
])
def test_invalid_release_context_or_budget_fails_before_deployment(source_event, key, value):
    with pytest.raises(ValueError):
        acceptance.validate_config({**context(), "RELEASE_SOURCE_EVENT": source_event, key: value})


def evidence(tmp_path):
    agents = tmp_path / "agent-live"
    for suite in acceptance.SUITES:
        directory = agents / suite
        directory.mkdir(parents=True)
        (directory / "report.json").write_text(json.dumps({"status": "PASS", "test_commit": SHA,
            "deployed_commit": SHA, "test_commit_matches_deployment": True, "deployment_unchanged": True}))
    fairness = {"measurement": "live_generated_contract_checks", "objective_passed": True,
                "requested_pairs": 19, "passed_pairs": 19, "human_review_status": "pending",
                "dataset_sha256": hashlib.sha256(acceptance.FAIRNESS.read_bytes()).hexdigest(),
                "pairs": [{"pair_id": pair["id"], "repeat": 1, "passed": True}
                          for pair in acceptance.load_pairs(acceptance.FAIRNESS)],
                "execution": {"commit_sha": SHA, "model_provider": "openai", "model_id": "gpt-6-luna",
                              "repeats": 1, "requested_runs": 38,
                              "completed_requested_runs": True, "token_usage_complete": True, "usage_unknown": False}}
    cases = json.loads((ROOT / "security/promptfoo/cases.json").read_text())
    count = sum(len(case["providers"]) for case in cases) * 2
    security = {"evaluation": {"mode": "live", "test_commit": SHA, "complete": True,
                "usage_complete": True, "budget_exhausted": False, "case_pattern": None,
                "repeats": 2, "planned_cases": count,
                "case_sha256": hashlib.sha256((ROOT / "security/promptfoo/cases.json").read_bytes()).hexdigest(),
                "grader_sha256": hashlib.sha256((ROOT / "security/promptfoo/assertions.cjs").read_bytes()).hexdigest()},
                "results": {"results": [{"success": True}] * count}}
    (tmp_path / "fairness.json").write_text(json.dumps(fairness))
    (tmp_path / "promptfoo-live.json").write_text(json.dumps(security))
    return agents, fairness, security


def test_complete_objective_evidence_passes_with_human_review_separately_pending(tmp_path):
    acceptance.validate_config(context())
    agents, _, _ = evidence(tmp_path)
    report = acceptance.assess(tmp_path, SHA, agent_root=agents)
    assert report["passed"] and len(report["checks"]) == 9
    assert report["human_semantic_acceptance"].startswith("pending")


@pytest.mark.parametrize("group,change", [
    ("fairness", {"objective_passed": False}), ("fairness", {"requested_pairs": 18}),
    ("fairness", {"passed_pairs": 18}), ("fairness", {"pairs": []}),
    ("fairness", {"pairs": None}), ("fairness", {"execution": None}),
    ("fairness", {"dataset_sha256": "changed"}), ("fairness", {"measurement": "offline_fixture_contract"}),
    ("fairness-execution", {"commit_sha": "b" * 40}), ("fairness-execution", {"usage_unknown": True}),
    ("fairness-execution", {"completed_requested_runs": False}),
    ("fairness-execution", {"repeats": 2}), ("fairness-execution", {"requested_runs": 76}),
    ("security", {"complete": False}), ("security", {"test_commit": "b" * 40}),
    ("security", {"case_pattern": "subset"}), ("security", {"usage_complete": False}),
    ("security", {"case_sha256": "changed"}), ("security", {"grader_sha256": "changed"}),
    ("security", {"budget_exhausted": True}), ("security", {"mode": "offline"}),
    ("security", {"planned_cases": 0}), ("security", {"repeats": 1}),
])
def test_wrong_incomplete_fixture_or_unaccounted_evidence_cannot_pass(tmp_path, group, change):
    agents, fairness, security = evidence(tmp_path)
    if group == "fairness":
        fairness.update(change)
    elif group == "fairness-execution":
        fairness["execution"].update(change)
    else:
        security["evaluation"].update(change)
    (tmp_path / "fairness.json").write_text(json.dumps(fairness))
    (tmp_path / "promptfoo-live.json").write_text(json.dumps(security))
    assert not acceptance.assess(tmp_path, SHA, agent_root=agents)["passed"]


@pytest.mark.parametrize("change", [{"status": "FAIL"}, {"status": "NOT RUN"},
    {"test_commit": "b" * 40}, {"deployed_commit": "b" * 40}, {"deployment_unchanged": False}])
def test_agent_failure_or_wrong_build_blocks_acceptance(tmp_path, change):
    agents, _, _ = evidence(tmp_path)
    path = agents / "budget/report.json"
    report = json.loads(path.read_text())
    report.update(change)
    path.write_text(json.dumps(report))
    assert not acceptance.assess(tmp_path, SHA, agent_root=agents)["passed"]


@pytest.mark.parametrize("change", ["duplicate", "repeat", "wrong-id", "failed"])
def test_every_authored_fairness_pair_must_pass_exactly_once(tmp_path, change):
    agents, fairness, _ = evidence(tmp_path)
    if change == "duplicate":
        fairness["pairs"][1] = fairness["pairs"][0]
    else:
        field, value = {"repeat": ("repeat", 2), "wrong-id": ("pair_id", "unknown"),
                        "failed": ("passed", False)}[change]
        fairness["pairs"][0][field] = value
    (tmp_path / "fairness.json").write_text(json.dumps(fairness))
    assert not acceptance.assess(tmp_path, SHA, agent_root=agents)["passed"]


def test_missing_reports_fail_and_publish_each_incomplete_group(tmp_path, monkeypatch):
    report = acceptance.assess(tmp_path, SHA, agent_root=tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    acceptance.publish(report, tmp_path)
    assert not report["passed"] and not any(row["passed"] for row in report["checks"])
    assert "FAIL / incomplete" in (tmp_path / "summary.md").read_text()


@pytest.mark.parametrize("complete", [True, False])
def test_gate_cli_exit_status_and_published_result_control_release_failure(tmp_path, monkeypatch, complete):
    agents, fairness, _ = evidence(tmp_path)
    if not complete:
        fairness["pairs"].pop()
        (tmp_path / "fairness.json").write_text(json.dumps(fairness))
    assess = acceptance.assess
    monkeypatch.setattr(acceptance, "OUTPUT", tmp_path)
    monkeypatch.setattr(acceptance, "assess", lambda directory, sha, **kwargs: assess(directory, sha, agent_root=agents, **kwargs))
    monkeypatch.setenv("RELEASE_SHA", SHA)
    monkeypatch.setenv("RELEASE_LIVE_SELECTION", json.dumps(ALL_LIVE))
    monkeypatch.setenv("RELEASE_JOB_RESULTS", json.dumps({job: {"result": "success"} for job in acceptance.RELEASE_JOBS}))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert acceptance.main(["--mode", "gate"]) == (0 if complete else 1)
    report = json.loads((tmp_path / "acceptance.json").read_text())
    assert report["passed"] is complete and report["release_sha"] == SHA


def workflows():
    return [yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(), Loader=yaml.BaseLoader)
            for name in ("ci", "release")]


def test_split_release_requires_preflight_scan_smoke_and_selected_live_stages():
    ci, release = workflows()
    assert "live" not in ci["jobs"] and "security-live" not in ci["jobs"]
    assert "inputs" not in (ci["on"]["workflow_dispatch"] or {})
    assert "github.event_name != 'push'" in ci["jobs"]["container-build"]["if"]
    jobs = release["jobs"]
    assert jobs["build-images"]["needs"] == ["release-gate", "live-preflight"]
    assert jobs["deploy-demo"]["needs"] == ["release-gate", "build-images", "corpus"]
    assert jobs["smoke"]["needs"] == ["deploy-demo"]
    assert jobs["security-live"]["needs"] == ["live-preflight", "deploy-demo", "smoke"]
    assert jobs["fairness"]["needs"] == ["live-preflight", "deploy-demo", "smoke", "security-live"]
    assert jobs["live"]["needs"] == ["live-preflight", "deploy-demo", "smoke", "security-live", "fairness"]
    assert set(jobs["live-acceptance"]["needs"]) == set(acceptance.RELEASE_JOBS)
    assert jobs["rollback"]["needs"] == ["deploy-demo", "live-acceptance"]
    assert release["concurrency"] == {"group": "deploy-demo", "cancel-in-progress": "false"}
    assert jobs["live"]["strategy"]["matrix"]["suite"] == list(acceptance.SUITES)
    assert jobs["live"]["strategy"]["max-parallel"] == "1"
    assert jobs["live"]["strategy"]["fail-fast"] == "true"
    fairness_step = next(s for s in jobs["fairness"]["steps"] if s.get("id") == "fairness-live")
    assert "--repeats 1" in fairness_step["run"]
    assert "always()" in jobs["live-acceptance"]["if"] and "always()" in jobs["rollback"]["if"]
    assert not any(s.get("continue-on-error") == "true" for j in jobs.values() for s in j["steps"])
    credentials = next(s for s in jobs["security-live"]["steps"] if s.get("id") == "security-credentials")
    assert credentials["with"]["output-env-credentials"] == "false"
    for key in ("corpus", "deploy-demo"):
        steps = jobs[key]["steps"]
        guard = next(i for i, s in enumerate(steps) if s.get("id") == "current")
        for s in steps[guard + 1:]:
            assert "steps.current.outputs.deploy == 'true'" in s["if"]
    deployment = jobs["deploy-demo"]["steps"]
    for role, name in (("ai", "Deploy AI service"), ("backend", "Deploy application backend"),
                       ("frontend", "Deploy Streamlit frontend")):
        attempt = next(i for i, s in enumerate(deployment) if s.get("id") == "attempt-" + role)
        assert attempt < next(i for i, s in enumerate(deployment) if s.get("name") == name)
        assert f"steps.attempt-{role}.outputs.attempted" in jobs["deploy-demo"]["outputs"][role + "-attempted"]
    assert all(s["with"]["retention-days"] == "90" for j in jobs.values() for s in j["steps"]
               if s.get("uses", "").startswith("actions/upload-artifact"))
    for name in ("corpus", "deploy-demo", "smoke", "fairness", "security-live"):
        steps = jobs[name]["steps"]
        guard = next(i for i, s in enumerate(steps) if "--mode validate-context" in s.get("run", ""))
        protected = {"corpus": "Ingest and verify approved Bedrock corpora", "deploy-demo": "Deploy AI service",
                     "smoke": "Run health and AI safety smoke tests", "fairness": "Live fairness — all 19 pairs once",
                     "security-live": "Promptfoo — selected live security regressions"}[name]
        assert guard < next(i for i, s in enumerate(steps)
                            if (s.get("id") == "fairness-live" if name == "fairness" else s.get("name") == protected))


@pytest.mark.parametrize("job", acceptance.RELEASE_JOBS)
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", None])
def test_any_unsuccessful_or_missing_prerequisite_blocks_even_complete_files(tmp_path, monkeypatch, job, result):
    agents, _, _ = evidence(tmp_path)
    jobs = {name: {"result": "success"} for name in acceptance.RELEASE_JOBS}
    if result is None:
        del jobs[job]
    else:
        jobs[job]["result"] = result
    assess = acceptance.assess
    monkeypatch.setattr(acceptance, "OUTPUT", tmp_path)
    monkeypatch.setattr(acceptance, "assess", lambda directory, sha, **kwargs: assess(directory, sha, agent_root=agents, **kwargs))
    monkeypatch.setenv("RELEASE_SHA", SHA)
    monkeypatch.setenv("RELEASE_LIVE_SELECTION", json.dumps(ALL_LIVE))
    monkeypatch.setenv("RELEASE_JOB_RESULTS", json.dumps(jobs))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert acceptance.main(["--mode", "gate"]) == 1
    report = json.loads((tmp_path / "acceptance.json").read_text())
    assert not report["passed"]
    assert all(row["passed"] for row in report["checks"] if not row["check"].startswith("job:"))


@pytest.mark.parametrize("raw", [None, "", "invalid", "null", "[]", '{"smoke": null}'])
def test_malformed_job_results_fail_closed(raw):
    assert not any(row["passed"] for row in acceptance.assess_jobs(raw))


@pytest.mark.parametrize("source_event", ["push", "workflow_dispatch"])
@pytest.mark.parametrize("attempt", ["1", "2"])
def test_per_job_context_cli_prevents_paid_or_mutating_reruns(monkeypatch, source_event, attempt):
    for key, value in {**context(), "RELEASE_SOURCE_EVENT": source_event, "GITHUB_RUN_ATTEMPT": attempt}.items():
        monkeypatch.setenv(key, value)
    if attempt == "1":
        assert acceptance.main(["--mode", "validate-context"]) == 0
    else:
        with pytest.raises(ValueError, match="PAID_RELEASE_RERUN_REQUIRES_FRESH_CI"):
            acceptance.main(["--mode", "validate-context"])


def selected(job, states, *, cancelled=False, workflow_run=None):
    """Evaluate only Boolean/equality expressions from the actual job guards."""
    text = re.sub(r"github\.event\.workflow_run\.(\w+)",
                  lambda m: repr((workflow_run or {}).get(m[1], "")), job["if"])
    text = re.sub(r"needs\.([\w-]+)\.(outputs\.[\w-]+|result)",
                  lambda m: repr(states.get(m[1], {}).get(m[2], "")), text)
    text = (text.replace("always()", "True").replace("cancelled()", str(cancelled))
            .replace("&&", " and ").replace("||", " or "))
    text = re.sub(r"!(?!=)", " not ", text)

    def evaluate(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BoolOp):
            values = [evaluate(value) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp):
            assert isinstance(node.op, ast.Not)
            return not evaluate(node.operand)
        assert isinstance(node, ast.Compare) and len(node.ops) == 1
        left, right = evaluate(node.left), evaluate(node.comparators[0])
        assert isinstance(node.ops[0], (ast.Eq, ast.NotEq))
        return left == right if isinstance(node.ops[0], ast.Eq) else left != right

    allowed = evaluate(ast.parse("(" + text.strip() + ")", mode="eval").body)
    # GitHub implicitly adds success() unless a guard contains a status function.
    return allowed and ("always()" in job["if"] or all(states[name].get("result") == "success" for name in job.get("needs", [])))


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "schedule", "pull_request", ""])
@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled", "skipped"])
@pytest.mark.parametrize("branch", ["main", "feature"])
def test_release_gate_only_accepts_successful_push_or_manual_main_ci(event, conclusion, branch):
    _, release = workflows()
    assert release["on"] == {"workflow_run": {
        "workflows": ["CI and LLMSecOps"], "branches": ["main"], "types": ["completed"],
    }}
    source = {"event": event, "conclusion": conclusion, "head_branch": branch}
    expected = event in ("push", "workflow_dispatch") and conclusion == "success" and branch == "main"
    assert selected(release["jobs"]["release-gate"], {}, workflow_run=source) is expected


def successful_states(selection):
    states = {name: {"result": "success"} for name in acceptance.RELEASE_JOBS}
    states["release-gate"]["outputs.deploy"] = "true"
    states["corpus"]["outputs.deploy"] = "true"
    states["deploy-demo"].update({"outputs.deploy": "true", "outputs.ai-attempted": "true"})
    states["live-preflight"].update({"outputs." + key: str(value).lower() for key, value in selection.items()})
    for name, enabled in selection.items():
        states[name]["result"] = "success" if enabled else "skipped"
    return states


@pytest.mark.parametrize("enabled", list(product((False, True), repeat=3)))
def test_every_optional_combination_runs_selected_stages_and_accepts_only_their_evidence(tmp_path, monkeypatch, enabled):
    selection = dict(zip(acceptance.LIVE_FLAGS, enabled, strict=True))
    jobs = workflows()[1]["jobs"]
    states = successful_states(selection)
    for name in acceptance.LIVE_FLAGS:
        assert selected(jobs[name], states) is selection[name]
        assert not selected(jobs[name], states, cancelled=True)
    assert selected(jobs["live-acceptance"], states)
    agents, _, _ = evidence(tmp_path)
    if not selection["live"]:
        shutil.rmtree(agents)
    for job, filename in (("fairness", "fairness.json"), ("security-live", "promptfoo-live.json")):
        if not selection[job]:
            (tmp_path / filename).unlink()
    assess = acceptance.assess
    monkeypatch.setattr(acceptance, "OUTPUT", tmp_path)
    monkeypatch.setattr(acceptance, "assess", lambda directory, sha, **kwargs: assess(directory, sha, agent_root=agents, **kwargs))
    monkeypatch.setenv("RELEASE_SHA", SHA)
    monkeypatch.setenv("RELEASE_LIVE_SELECTION", json.dumps(selection))
    # Later variable edits cannot change the preflight snapshot used by the gate.
    for flag in acceptance.LIVE_FLAGS.values():
        monkeypatch.setenv(flag, "false")
    monkeypatch.setenv("RELEASE_JOB_RESULTS", json.dumps(states))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert acceptance.main(["--mode", "gate"]) == 0
    report = json.loads((tmp_path / "acceptance.json").read_text())
    assert report["live_selection"] == selection and report["passed"]
    assert report["live_evidence_complete"] is all(enabled)
    for row in report["checks"]:
        if not row["required"]:
            assert row["passed"] is None and row["status"].startswith("SKIPPED")
    states["live-acceptance"] = {"result": "success"}
    assert not selected(jobs["rollback"], states)
    for failure, requested in selection.items():
        if not requested:
            continue
        failed_states = successful_states(selection)
        failed_states[failure]["result"] = "failure"
        for later in list(acceptance.LIVE_FLAGS)[list(acceptance.LIVE_FLAGS).index(failure) + 1:]:
            assert not selected(jobs[later], failed_states)
        assert not acceptance.passed_checks(acceptance.assess_jobs(json.dumps(failed_states), selection))
        failed_states["live-acceptance"] = {"result": "failure"}
        assert selected(jobs["rollback"], failed_states)


@pytest.mark.parametrize("job", acceptance.LIVE_FLAGS)
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", None])
def test_enabled_stage_never_becomes_advisory_even_if_other_stages_disabled(job, result):
    selection = {name: name == job for name in acceptance.LIVE_FLAGS}
    states = successful_states(selection)
    if result is None:
        del states[job]
    else:
        states[job]["result"] = result
    assert not acceptance.passed_checks(acceptance.assess_jobs(json.dumps(states), selection))
    states["live-acceptance"] = {"result": "failure"}
    assert selected(workflows()[1]["jobs"]["rollback"], states)


@pytest.mark.parametrize("job", acceptance.LIVE_FLAGS)
def test_enabled_stage_still_requires_its_complete_live_evidence(tmp_path, job):
    selection = {name: name == job for name in acceptance.LIVE_FLAGS}
    report = acceptance.assess(tmp_path, SHA, agent_root=tmp_path, selection=selection)
    assert not report["passed"]
    assert any(row["required"] and row["passed"] is False for row in report["checks"])


@pytest.mark.parametrize("job", acceptance.REQUIRED_JOBS)
def test_mandatory_failure_still_rejects_release_with_every_live_stage_off(job):
    selection = dict.fromkeys(acceptance.LIVE_FLAGS, False)
    states = successful_states(selection)
    states[job]["result"] = "failure"
    assert not acceptance.passed_checks(acceptance.assess_jobs(json.dumps(states), selection))
    for name in acceptance.LIVE_FLAGS:
        assert not selected(workflows()[1]["jobs"][name], states)


@pytest.mark.parametrize("raw", [None, "", "null", "{}", '{"live": false}',
                                json.dumps({**ALL_LIVE, "live": "false"}),
                                json.dumps({**ALL_LIVE, "unexpected": False})])
def test_missing_or_malformed_selection_cannot_silently_disable_live_gate(tmp_path, monkeypatch, raw):
    agents, _, _ = evidence(tmp_path)
    assess = acceptance.assess
    monkeypatch.setattr(acceptance, "OUTPUT", tmp_path)
    monkeypatch.setattr(acceptance, "assess", lambda directory, sha, **kwargs: assess(directory, sha, agent_root=agents, **kwargs))
    monkeypatch.setenv("RELEASE_SHA", SHA)
    monkeypatch.setenv("RELEASE_JOB_RESULTS", json.dumps(successful_states(ALL_LIVE)))
    if raw is None:
        monkeypatch.delenv("RELEASE_LIVE_SELECTION", raising=False)
    else:
        monkeypatch.setenv("RELEASE_LIVE_SELECTION", raw)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert acceptance.main(["--mode", "gate"]) == 1
    report = json.loads((tmp_path / "acceptance.json").read_text())
    assert not next(row for row in report["checks"] if row["check"] == "live-selection")["passed"]
    assert report["selection_valid"] is False and report["live_selection"] is None


def test_live_settings_are_only_required_for_their_enabled_stage():
    env = {key: value for key, value in context().items()
           if key.startswith(("GITHUB_", "RELEASE_")) or key in ("SMOKE_BACKEND_API_KEY", "COACH_SMOKE_URL")}
    assert acceptance.validate_config(env) == dict.fromkeys(acceptance.LIVE_FLAGS, False)
    assert acceptance.validate_config({**env, "RUN_LIVE_AGENT_RAG": "true"})["live"]
    with pytest.raises(ValueError, match="SECURITY_TEST_ROLE"):
        acceptance.validate_config({**env, "RUN_LIVE_SECURITY": "true"})
    with pytest.raises(ValueError, match="LIVE_MODEL_INPUT_USD_PER_MILLION"):
        acceptance.validate_config({**env, "RUN_LIVE_FAIRNESS": "true"})
    for flag in acceptance.LIVE_FLAGS.values():
        with pytest.raises(ValueError, match=flag):
            acceptance.validate_config({**env, flag: "tru"})


@pytest.mark.parametrize("key", ["SMOKE_BACKEND_API_KEY", "COACH_SMOKE_URL"])
def test_smoke_configuration_is_required_even_when_all_live_stages_off(key):
    env = {**context(), **dict.fromkeys(acceptance.LIVE_FLAGS.values(), "false"), key: ""}
    with pytest.raises(ValueError, match=key):
        acceptance.validate_config(env)


def test_initialize_marks_disabled_matrix_reports_skipped_without_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(acceptance, "ROOT", tmp_path)
    monkeypatch.setattr(acceptance, "OUTPUT", tmp_path / "post-deploy")
    monkeypatch.setenv("RELEASE_SHA", SHA)
    monkeypatch.setenv("RELEASE_LIVE_SELECTION", json.dumps(dict.fromkeys(acceptance.LIVE_FLAGS, False)))
    assert acceptance.main(["--mode", "initialize"]) == 0
    for suite in acceptance.SUITES:
        report = json.loads((tmp_path / "artifacts/agent-live" / suite / "report.json").read_text())
        assert report["status"] == "SKIPPED" and report["gate"] == report["stage"] == "not_selected"
        assert report["records"] == []


def test_preflight_snapshots_flags_and_skips_secret_access_if_security_disabled(tmp_path, monkeypatch):
    output = tmp_path / "outputs"
    for key, value in context().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("RUN_LIVE_SECURITY", "false")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert acceptance.main(["--mode", "validate-config"]) == 0
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert values["security-live"] == "false" and values["fairness"] == values["live"] == "true"
    assert json.loads(values["live-selection"]) == {**ALL_LIVE, "security-live": False}
    jobs = workflows()[1]["jobs"]
    preflight = jobs["live-preflight"]
    for flag in acceptance.LIVE_FLAGS.values():
        assert preflight["env"][flag] == "${{ vars." + flag + " || 'false' }}"
    credential_steps = [s for s in preflight["steps"] if s.get("id") == "security-preflight-credentials"
                        or s.get("name") == "Verify live security secret access before deployment"]
    assert len(credential_steps) == 2
    assert all(s["if"] == "steps.selection.outputs.security-live == 'true'" for s in credential_steps)
    for step in jobs["live-acceptance"]["steps"]:
        if step.get("uses", "").startswith("actions/download-artifact"):
            assert "needs.live-preflight.outputs." in step["if"]


def test_disabled_stage_cannot_execute_unnoticed():
    selection = dict.fromkeys(acceptance.LIVE_FLAGS, False)
    states = successful_states(selection)
    states["fairness"]["result"] = "success"
    checks = acceptance.assess_jobs(json.dumps(states), selection)
    assert not acceptance.passed_checks(checks)
    assert next(row for row in checks if row["check"] == "job:fairness")["status"] == "FAIL / unexpected execution"


@pytest.mark.parametrize("failure", ["smoke", "fairness", "live", "security-live", "deploy-demo"])
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_failed_stage_stops_later_paid_jobs_and_still_selects_gate_and_rollback(failure, result):
    _, release = workflows()
    jobs = release["jobs"]
    states = successful_states(ALL_LIVE)
    states[failure]["result"] = result
    if failure == "smoke":
        assert not selected(jobs["security-live"], states)
        states["security-live"]["result"] = "skipped"
    if failure in ("smoke", "security-live"):
        assert not selected(jobs["fairness"], states)
        states["fairness"]["result"] = "skipped"
    if failure in ("smoke", "security-live", "fairness"):
        assert not selected(jobs["live"], states)
    assert selected(jobs["live-acceptance"], states)
    states["live-acceptance"] = {"result": "failure"}
    assert selected(jobs["rollback"], states)


@pytest.mark.parametrize("reason", ["accepted", "predeployment-failure", "stale-corpus", "stale-deploy"])
def test_success_and_no_service_change_never_select_rollback(reason):
    _, release = workflows()
    states = {name: {"result": "success"} for name in acceptance.RELEASE_JOBS}
    states["release-gate"]["outputs.deploy"] = "true"
    states["corpus"]["outputs.deploy"] = "true"
    states["deploy-demo"].update({"outputs.deploy": "true", "outputs.ai-attempted": "true"})
    states["live-acceptance"] = {"result": "success"}
    if reason == "predeployment-failure":
        states["deploy-demo"] = {"result": "skipped"}
        states["live-acceptance"]["result"] = "failure"
    elif reason.startswith("stale-"):
        states["corpus" if reason == "stale-corpus" else "deploy-demo"]["outputs.deploy"] = "false"
        assert not selected(release["jobs"]["live-acceptance"], states)
    assert not selected(release["jobs"]["rollback"], states)


@pytest.mark.parametrize("attempted", [("AI",), ("AI", "BACKEND"), ("AI", "BACKEND", "FRONTEND")])
def test_real_rollback_shell_restores_only_attempted_services(tmp_path, attempted):
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parents[1] / "bin/bash.exe" if git else None
        if not candidate or not candidate.is_file():
            pytest.skip("Rollback shell test requires Git Bash")
        bash = str(candidate)
    if not bash:
        pytest.skip("Rollback shell test requires Bash")
    _, release = workflows()
    script = next(step["run"] for step in release["jobs"]["rollback"]["steps"]
                  if step.get("name") == "Roll back services when post-deploy checks fail")
    log = tmp_path / "rollback.log"
    env = {**os.environ, "ECS_CLUSTER": "test-cluster", "ROLLBACK_LOG": log.as_posix()}
    for role in ("AI", "BACKEND", "FRONTEND"):
        env.update({role + "_DEPLOYED": "true" if role in attempted else "false", role + "_SERVICE": role.lower(),
                    role + "_PREVIOUS_TASK_DEFINITION": role.lower() + "-previous"})
    stub = 'aws() { printf "%s\\n" "$*" >> "$ROLLBACK_LOG"; };\n'
    result = subprocess.run([bash, "-eu", "-c", stub + script], env=env, capture_output=True,
                            text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == len(attempted) + 1
    assert all(f"--task-definition {role.lower()}-previous" in calls[i] for i, role in enumerate(attempted))
    assert calls[-1].endswith("--services " + " ".join(role.lower() for role in attempted))


@pytest.mark.parametrize("invalid", [False, True])
def test_capture_exports_family_revision_without_masked_account_and_rejects_invalid_revisions(tmp_path, invalid):
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parents[1] / "bin/bash.exe" if git else None
        if not candidate or not candidate.is_file():
            pytest.skip("Capture shell test requires Git Bash")
        bash = str(candidate)
    if not bash:
        pytest.skip("Capture shell test requires Bash")
    _, release = workflows()
    script = next(s["run"] for s in release["jobs"]["deploy-demo"]["steps"] if s.get("id") == "rollback-state")
    output = tmp_path / "outputs"
    env = {**os.environ, "ECS_CLUSTER": "synthetic", "GITHUB_ENV": (tmp_path / "env").as_posix(),
           "GITHUB_OUTPUT": output.as_posix(), "INVALID_REVISION": str(invalid)}
    for role in ("AI", "BACKEND", "FRONTEND"):
        env.update({role + "_CHANGED": "true", role + "_SERVICE": role.lower()})
    stub = '''aws() {
      case "$*" in
        *deploymentCircuitBreaker*) echo True ;;
        *taskDefinition*)
          if [[ "$INVALID_REVISION" == True ]]; then echo None;
          else echo arn:aws:ecs:ap-southeast-1:123456789012:task-definition/synthetic-family:42; fi ;;
        *) return 1 ;;
      esac
    }
    '''
    result = subprocess.run([bash, "-eu", "-c", stub + script], env=env, capture_output=True,
                            text=True, timeout=10, check=False)
    if invalid:
        assert result.returncode != 0 and not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        values = dict(line.split("=", 1) for line in output.read_text().splitlines())
        assert values == {role + "-previous-task-definition": "synthetic-family:42" for role in ("ai", "backend", "frontend")}
        assert "123456789012" not in output.read_text()
