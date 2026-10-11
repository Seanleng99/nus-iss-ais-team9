"""Require complete live evidence for the exact deployed release; publish failures too."""
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path

from infra.scripts.agent_live_evaluation import SUITES, initial_report, write_report
from infra.scripts.fairness_live_evaluation import load_pairs

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/post-deploy"
FAIRNESS = ROOT / "apps/ai-service/app/evals/datasets/fairness_consistency.jsonl"
REQUIRED_JOBS = ("release-gate", "live-preflight", "build-images", "corpus", "deploy-demo",
                 "smoke", "fairness", "live", "security-live")


def require_release_context(env):
    if (env.get("GITHUB_EVENT_NAME") != "workflow_run" or env.get("GITHUB_REF") != "refs/heads/main"
            or env.get("RELEASE_SOURCE_EVENT") != "push" or env.get("RELEASE_SOURCE_CONCLUSION") != "success"
            or not re.fullmatch(r"[a-f0-9]{40}", env.get("RELEASE_SHA", ""))):
        raise ValueError("LIVE_REQUIRES_SUCCESSFUL_MAIN_RELEASE")
    if env.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("PAID_RELEASE_RERUN_REQUIRES_FRESH_CI")


def validate_config(env):
    require_release_context(env)
    for key in ("SMOKE_BACKEND_API_KEY", "COACH_SMOKE_URL", "SECURITY_TEST_ROLE", "INVESTMENT_TEST_OPENAI_SECRET_ID"):
        if not env.get(key, "").strip():
            raise ValueError(f"Missing live release setting: {key}")
    for key in ("LIVE_MODEL_INPUT_USD_PER_MILLION", "LIVE_MODEL_OUTPUT_USD_PER_MILLION", "FAIRNESS_LIVE_MAX_COST_USD"):
        try:
            value = float(env.get(key, ""))
        except ValueError:
            raise ValueError(f"Invalid live release setting: {key}") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid live release setting: {key}")


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def assess_jobs(raw):
    """A failed/cancelled/skipped prerequisite cannot be masked by passing files."""
    try:
        jobs = json.loads(raw)
    except (TypeError, ValueError):
        jobs = {}
    jobs = jobs if isinstance(jobs, dict) else {}
    checks = []
    for name in REQUIRED_JOBS:
        job = jobs.get(name)
        result = job.get("result") if isinstance(job, dict) else None
        checks.append({"check": "job:" + name, "passed": result == "success",
                       "result": result or "missing"})
    return checks


def assess(directory, sha, *, agent_root=None):
    agent_root = agent_root or ROOT / "artifacts/agent-live"
    results = []
    for suite in SUITES:
        report = read_json(agent_root / suite / "report.json")
        passed = (report.get("status") == "PASS" and report.get("test_commit") == sha
                  and report.get("deployed_commit") == sha and report.get("test_commit_matches_deployment") is True
                  and report.get("deployment_unchanged") is True)
        results.append({"check": suite, "passed": passed})
    fairness = read_json(directory / "fairness.json")
    expected_pairs = {(pair["id"], 1) for pair in load_pairs(FAIRNESS)}
    planned = len(expected_pairs)
    pairs = fairness.get("pairs", [])
    live = fairness.get("execution", {})
    pairs_valid = (isinstance(pairs, list) and len(pairs) == planned
                   and all(isinstance(row, dict) and isinstance(row.get("pair_id"), str)
                           and row.get("repeat") == 1 and row.get("passed") is True for row in pairs)
                   and {(row["pair_id"], row["repeat"]) for row in pairs} == expected_pairs)
    live = live if isinstance(live, dict) else {}
    passed = (fairness.get("measurement") == "live_generated_contract_checks"
              and fairness.get("objective_passed") is True and live.get("commit_sha") == sha
              and live.get("model_provider") == "openai" and live.get("model_id") == "gpt-6-luna"
              and fairness.get("requested_pairs") == planned and fairness.get("passed_pairs") == planned
              and live.get("repeats") == 1 and live.get("requested_runs") == planned * 2 and pairs_valid
              and fairness.get("dataset_sha256") == hashlib.sha256(FAIRNESS.read_bytes()).hexdigest()
              and live.get("completed_requested_runs") is True and live.get("token_usage_complete") is True
              and live.get("usage_unknown") is False)
    results.append({"check": "fairness", "passed": passed,
                    "human_review_status": fairness.get("human_review_status", "pending")})
    security = read_json(directory / "promptfoo-live.json")
    evaluation = security.get("evaluation", {})
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    security_results = security.get("results", {})
    rows = security_results.get("results", []) if isinstance(security_results, dict) else []
    cases = json.loads((ROOT / "security/promptfoo/cases.json").read_text(encoding="utf-8"))
    planned = sum(len(case["providers"]) for case in cases) * 2
    passed = (evaluation.get("mode") == "live" and evaluation.get("test_commit") == sha
              and evaluation.get("complete") is True and evaluation.get("usage_complete") is True
              and evaluation.get("budget_exhausted") is False and evaluation.get("case_pattern") is None
              and evaluation.get("repeats") == 2 and evaluation.get("planned_cases") == planned
              and isinstance(rows, list) and len(rows) == planned
              and all(isinstance(row, dict) and row.get("success") is True for row in rows)
              and evaluation.get("case_sha256") == hashlib.sha256((ROOT / "security/promptfoo/cases.json").read_bytes()).hexdigest()
              and evaluation.get("grader_sha256") == hashlib.sha256((ROOT / "security/promptfoo/assertions.cjs").read_bytes()).hexdigest())
    results.append({"check": "live-security", "passed": passed,
                    "measurement": "live-model regressions against release source and governed local corpora"})
    return {"schema_version": 1, "release_sha": sha, "passed": all(row["passed"] for row in results),
            "checks": results, "human_semantic_acceptance": "pending; automated contract gate only"}


def publish(report, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Required post-deployment live acceptance", "",
             f"Release: `{report['release_sha']}`. Automated result: **{'PASS' if report['passed'] else 'FAIL / incomplete'}**.",
             "Failures block release acceptance and trigger service rollback. Human semantic/fairness review remains pending.",
             "", "| Check | Result |", "|---|---|"]
    lines += [f"| {row['check']} | {'PASS' if row['passed'] else 'FAIL / incomplete'} |" for row in report["checks"]]
    lines += ["", "Live security exercises release source with real model calls and governed local corpora; agent/fairness suites exercise the deployed API/AWS.",
              "Full synthetic answers, paired diagnostics, usage and blinded review forms are retained in this artifact."]
    markdown = "\n".join(lines) + "\n"
    (directory / "summary.md").write_text(markdown, encoding="utf-8")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(markdown)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("validate-context", "validate-config", "initialize", "summarize", "gate"))
    args = parser.parse_args(argv)
    if args.mode == "validate-context":
        require_release_context(os.environ)
    elif args.mode == "validate-config":
        validate_config(os.environ)
    elif args.mode == "initialize":
        for suite in SUITES:
            write_report(initial_report(suite), ROOT / "artifacts/agent-live" / suite)
        OUTPUT.mkdir(parents=True, exist_ok=True)
    else:
        report = assess(OUTPUT, os.environ["RELEASE_SHA"])
        report["checks"].extend(assess_jobs(os.getenv("RELEASE_JOB_RESULTS")))
        report["passed"] = all(row["passed"] for row in report["checks"])
        publish(report, OUTPUT)
        if args.mode == "gate" and not report["passed"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
