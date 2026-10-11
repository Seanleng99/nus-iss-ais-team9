"""Execution ownership and cost boundaries for the single CI entry point."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def workflow(name="ci"):
    return yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(), Loader=yaml.BaseLoader)


def test_all_pre_release_tests_have_one_workflow_entry_point():
    ci = workflow()
    assert not (ROOT / ".github/workflows/agent-evaluations.yml").exists()
    assert not (ROOT / ".github/workflows/project-security-scan.yml").exists()
    assert all("uses" not in job for job in ci["jobs"].values())
    assert "paths-ignore" not in ci["on"]["push"]
    assert "paths-ignore" not in ci["on"]["pull_request"]
    for name in ("offline", "metrics", "ai-service", "frontend", "backend",
                 "project-security-scan", "infrastructure", "service-integration"):
        assert name in ci["jobs"]


def test_infrastructure_tests_have_one_owner_and_bootstrap_tests_are_excluded():
    jobs = workflow()["jobs"]
    infrastructure = next(s["run"] for s in jobs["infrastructure"]["steps"]
                          if s.get("name") == "Test deployment and operational scripts")
    assert "--ignore=infra/scripts/tests/test_detect_changes.py" in infrastructure
    assert "--ignore=infra/scripts/tests/test_deployment_baseline.py" in infrastructure
    for job in ("ai-service", "project-security-scan"):
        for step in jobs[job]["steps"]:
            run = step.get("run", "")
            assert not ("infra/scripts/tests/test_" in run and any(
                command in run for command in ("pytest", "unittest")))


def test_platform_job_has_explicit_ownership_and_separate_shared_evidence():
    jobs = workflow()["jobs"]
    job = jobs["ai-service"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "check_test_ownership.py" in commands
    assert "--suite platform" in commands and "--suite shared" in commands
    assert "--suite remaining" not in commands and "test_conversational_pipeline.py" not in commands
    assert "needs.changes.outputs.deploy == 'true'" in job["if"]
    assert "ai-service" in jobs["agent-test-gate"]["needs"]
    assert "PLATFORM_RESULT" in jobs["agent-test-gate"]["env"]
    artifacts = {step["with"]["name"] for step in job["steps"]
                 if step.get("uses", "").startswith("actions/upload-artifact")}
    assert artifacts == {"agent-offline-platform", "shared-library-contracts"}


def test_metrics_artifact_retains_every_required_dataset_including_fairness():
    policy = json.loads((ROOT / "infra/llmsecops/evaluation-policy.json").read_text())
    artifact = next(step["with"] for step in workflow()["jobs"]["metrics"]["steps"]
                    if step.get("uses", "").startswith("actions/upload-artifact"))
    retained = set(artifact["path"].splitlines())
    assert {suite["dataset"] for suite in policy["suites"]} <= retained
    assert "apps/ai-service/app/evals/datasets/fairness_consistency.jsonl" in retained


@pytest.mark.parametrize("suite,artifact,accepted", [
    ("platform", "agent-offline-platform", True),
    ("shared", "shared-library-contracts", False),
])
def test_common_contract_reports_are_visible_and_failed_acceptance_stays_failed(tmp_path, suite, artifact, accepted):
    from infra.scripts.summarize_agent_evaluations import collect, render, render_html
    directory = tmp_path / artifact
    directory.mkdir()
    evidence = {"accepted": accepted, "measurement": "offline", "datasets": [], "metrics": [],
                "acceptance_criteria": [], "limitations": "synthetic", "results": {"cases": []}}
    (directory / f"{suite}-evaluation.json").write_text(json.dumps(evidence))
    reports = collect(tmp_path, live_requested=False, live_job_result="skipped")
    row = next(row for row in reports if row["suite"] == suite)
    assert row["status"] == ("PASS" if accepted else "FAIL")
    assert f"{suite} contracts" in render(reports)
    assert f"{suite}-offline" in render_html(reports)


def test_main_push_builds_in_release_and_live_acceptance_is_in_release():
    jobs = workflow()["jobs"]
    assert "github.event_name != 'push'" in jobs["container-build"]["if"]
    assert "live" not in jobs and "security-live" not in jobs
    assert not workflow()["on"]["workflow_dispatch"]
    assert "live" not in jobs["agent-test-gate"]["needs"]
    assert "security-live" not in jobs["report"]["needs"]


def test_stale_release_skips_every_mutating_or_acceptance_step():
    steps = workflow("release")["jobs"]["deploy-demo"]["steps"]
    guard = next(i for i, step in enumerate(steps) if step.get("id") == "current")
    assert "deploy=false" in steps[guard]["run"]
    assert "exit 1" not in steps[guard]["run"]
    for step in steps[guard + 1:]:
        assert "steps.current.outputs.deploy == 'true'" in step["if"], step.get("name")


@pytest.mark.parametrize("latest,exit_code,expected", [("a" * 40, 0, "true"), ("b" * 40, 0, "false"), ("", 1, None)])
def test_final_release_guard_executes_safely(tmp_path, latest, exit_code, expected):
    bash = shutil.which("bash")
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parents[1] / "bin/bash.exe" if git else None
        if candidate is None or not candidate.is_file():
            pytest.skip("CI shell guard requires Git Bash on Windows")
        bash = str(candidate)
    if not bash:
        pytest.skip("CI shell guard requires bash")
    script = next(s["run"] for s in workflow("release")["jobs"]["deploy-demo"]["steps"] if s.get("id") == "current")
    gh = tmp_path / "gh"
    gh.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_SHA"\nexit "$TEST_EXIT"\n')
    gh.chmod(0o700)
    output = tmp_path / "outputs"
    result = subprocess.run([bash, "-eu", "-c", script], capture_output=True, text=True, timeout=10, check=False,
                            env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                                 "TEST_SHA": latest, "TEST_EXIT": str(exit_code), "RELEASE_SHA": "a" * 40,
                                 "GITHUB_REPOSITORY": "test/repo", "GITHUB_OUTPUT": output.as_posix(),
                                 "GITHUB_STEP_SUMMARY": (tmp_path / "summary").as_posix()})
    assert result.returncode == exit_code, result.stderr
    assert (output.read_text().strip() if output.exists() else None) == (f"deploy={expected}" if expected else None)


def test_combined_index_keeps_failed_status_and_links_all_evidence(tmp_path):
    from infra.scripts.summarize_agent_evaluations import ci_overview
    evidence = tmp_path / "security"
    evidence.mkdir()
    (evidence / "failed scan.json").write_text('{"passed": false}')
    markdown, page = ci_overview([{"job": "security-live", "result": "failure"}], tmp_path)
    assert "failure" in markdown and "failure" in page
    assert "evidence/security/failed%20scan.json" in page
    assert "Failed or missing case evidence cannot establish acceptance" in page


def test_advisory_security_job_success_does_not_hide_failed_acceptance(tmp_path):
    from infra.scripts.summarize_agent_evaluations import ci_overview
    (tmp_path / "promptfoo-live-status.json").write_text('{"status": "FAIL"}')
    markdown, page = ci_overview([{"job": "security-live", "result": "success"}], tmp_path)
    assert "Live security acceptance (actual evidence) | FAIL" in markdown
    assert "<td>FAIL</td>" in page


def test_combined_report_command_copies_evidence_and_keeps_missing_tests_unaccepted(tmp_path, monkeypatch):
    from infra.scripts import summarize_agent_evaluations as report
    source, output = tmp_path / "collected", tmp_path / "report"
    source.mkdir()
    (source / "promptfoo-live-status.json").write_text('{"status": "FAIL"}')
    monkeypatch.setenv("CI_JOB_RESULTS", '{"security-live": {"result": "success"}}')
    monkeypatch.setenv("LIVE_REQUESTED", "true")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr("sys.argv", ["report", "--input", str(source), "--output", str(output)])
    report.main()
    assert (output / "evidence/promptfoo-live-status.json").is_file()
    assert "<td>FAIL</td>" in (output / "index.html").read_text()
    assert all(row["status"] != "PASS" for row in json.loads((output / "report.json").read_text()))
