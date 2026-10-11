"""Exercise the required release gate using synthetic reports, never paid calls."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from infra.scripts import post_deploy_acceptance as acceptance

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40


def context():
    return {"GITHUB_EVENT_NAME": "workflow_run", "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ATTEMPT": "1",
            "RELEASE_SOURCE_EVENT": "push", "RELEASE_SOURCE_CONCLUSION": "success", "RELEASE_SHA": SHA,
            "SMOKE_BACKEND_API_KEY": "synthetic-key", "COACH_SMOKE_URL": "https://example.test/api/coach",
            "SECURITY_TEST_ROLE": "synthetic-role", "INVESTMENT_TEST_OPENAI_SECRET_ID": "synthetic-secret-id",
            "LIVE_MODEL_INPUT_USD_PER_MILLION": "1", "LIVE_MODEL_OUTPUT_USD_PER_MILLION": "1",
            "FAIRNESS_LIVE_MAX_COST_USD": "1"}


@pytest.mark.parametrize("key,value", [
    ("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/feature"), ("GITHUB_RUN_ATTEMPT", "2"),
    ("RELEASE_SOURCE_EVENT", "pull_request"), ("RELEASE_SOURCE_CONCLUSION", "failure"), ("RELEASE_SHA", ""),
    ("SMOKE_BACKEND_API_KEY", ""), ("SECURITY_TEST_ROLE", ""), ("LIVE_MODEL_INPUT_USD_PER_MILLION", ""),
    ("LIVE_MODEL_INPUT_USD_PER_MILLION", "nan"), ("LIVE_MODEL_OUTPUT_USD_PER_MILLION", "inf"),
    ("FAIRNESS_LIVE_MAX_COST_USD", "0"), ("FAIRNESS_LIVE_MAX_COST_USD", "-1"),
])
def test_invalid_release_context_or_budget_fails_before_deployment(key, value):
    with pytest.raises(ValueError):
        acceptance.validate_config({**context(), key: value})


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
    monkeypatch.setattr(acceptance, "assess", lambda directory, sha: assess(directory, sha, agent_root=agents))
    monkeypatch.setenv("RELEASE_SHA", SHA)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert acceptance.main(["--mode", "gate"]) == (0 if complete else 1)
    report = json.loads((tmp_path / "acceptance.json").read_text())
    assert report["passed"] is complete and report["release_sha"] == SHA


def workflows():
    return [yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(), Loader=yaml.BaseLoader)
            for name in ("ci", "release")]


def test_live_stages_move_to_release_before_rollback_and_image_scan_stays_before_deploy():
    ci, release = workflows()
    assert "live" not in ci["jobs"] and "security-live" not in ci["jobs"]
    assert "inputs" not in (ci["on"]["workflow_dispatch"] or {})
    assert "github.event_name != 'push'" in ci["jobs"]["container-build"]["if"]
    assert release["jobs"]["deploy-demo"]["needs"] == ["release-gate", "build-images"]
    steps = release["jobs"]["deploy-demo"]["steps"]
    names = [step.get("name") for step in steps]
    assert names.index("Validate required live acceptance configuration") < names.index("Deploy AI service")
    smoke, gate, rollback = (names.index(name) for name in ("Run health and AI safety smoke tests",
        "Require complete live release acceptance", "Roll back services when post-deploy checks fail"))
    fairness_step = steps[names.index("Live fairness — all 19 pairs once")]
    assert "--repeats 1" in fairness_step["run"]
    assert smoke < names.index("Live fairness — all 19 pairs once") < gate < rollback
    assert smoke < names.index("Live agent and RAG release contracts") < gate
    assert smoke < names.index("Promptfoo — required live security regressions") < gate
    assert "always()" in steps[gate]["if"] and "failure()" in steps[rollback]["if"]
    assert not any(step.get("continue-on-error") == "true" for step in steps)
    credentials = next(step for step in steps if step.get("id") == "security-credentials")
    assert credentials["with"]["output-env-credentials"] == "false"
    for step in steps[names.index("Verify release is still current main") + 1:]:
        assert "steps.current.outputs.deploy == 'true'" in step["if"]


def test_real_rollback_shell_restores_all_captured_services(tmp_path):
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
    script = next(step["run"] for step in release["jobs"]["deploy-demo"]["steps"]
                  if step.get("name") == "Roll back services when post-deploy checks fail")
    log = tmp_path / "rollback.log"
    env = {**os.environ, "ECS_CLUSTER": "test-cluster", "ROLLBACK_LOG": log.as_posix()}
    for role in ("AI", "BACKEND", "FRONTEND"):
        env.update({role + "_DEPLOYED": "true", role + "_SERVICE": role.lower(),
                    role + "_PREVIOUS_TASK_DEFINITION": role.lower() + "-previous"})
    stub = 'aws() { printf "%s\\n" "$*" >> "$ROLLBACK_LOG"; };\n'
    result = subprocess.run([bash, "-eu", "-c", stub + script], env=env, capture_output=True,
                            text=True, timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert len(calls) == 4
    assert all(f"--task-definition {role}-previous" in calls[i] for i, role in enumerate(("ai", "backend", "frontend")))
    assert calls[-1].endswith("--services ai backend frontend")
