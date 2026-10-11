"""Gate mandatory release jobs and selected live stages; publish skipped stages too."""
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
REQUIRED_JOBS = ("release-gate", "live-preflight", "build-images", "corpus", "deploy-demo", "smoke")
LIVE_FLAGS = {"security-live": "RUN_LIVE_SECURITY", "fairness": "RUN_LIVE_FAIRNESS",
              "live": "RUN_LIVE_AGENT_RAG"}
RELEASE_JOBS = (*REQUIRED_JOBS, *LIVE_FLAGS)


def live_selection(env):
    selection = {}
    for job, flag in LIVE_FLAGS.items():
        value = env.get(flag, "false") or "false"
        if value not in ("true", "false"):
            raise ValueError(f"Invalid optional live setting: {flag}; use true or false")
        selection[job] = value == "true"
    return selection


def parse_selection(raw):
    try:
        selection = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("Missing or invalid release live selection") from None
    if (not isinstance(selection, dict) or set(selection) != set(LIVE_FLAGS)
            or any(type(value) is not bool for value in selection.values())):
        raise ValueError("Missing or invalid release live selection")
    return selection


def complete_selection(selection):
    """Require all live stages unless a complete explicit snapshot is supplied."""
    return dict.fromkeys(LIVE_FLAGS, True) if selection is None else parse_selection(json.dumps(selection))


def passed_checks(checks):
    return all(row.get("policy_satisfied", row["passed"]) is True for row in checks)


def require_release_context(env):
    if (env.get("GITHUB_EVENT_NAME") != "workflow_run" or env.get("GITHUB_REF") != "refs/heads/main"
            or env.get("RELEASE_SOURCE_EVENT") not in ("push", "workflow_dispatch")
            or env.get("RELEASE_SOURCE_CONCLUSION") != "success"
            or not re.fullmatch(r"[a-f0-9]{40}", env.get("RELEASE_SHA", ""))):
        raise ValueError("LIVE_REQUIRES_SUCCESSFUL_MAIN_RELEASE")
    if env.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ValueError("PAID_RELEASE_RERUN_REQUIRES_FRESH_CI")


def validate_config(env):
    require_release_context(env)
    selection = live_selection(env)
    required = ["SMOKE_BACKEND_API_KEY", "COACH_SMOKE_URL"]
    if selection["security-live"]:
        required += ["SECURITY_TEST_ROLE", "INVESTMENT_TEST_OPENAI_SECRET_ID"]
    for key in required:
        if not env.get(key, "").strip():
            raise ValueError(f"Missing live release setting: {key}")
    rates = ("LIVE_MODEL_INPUT_USD_PER_MILLION", "LIVE_MODEL_OUTPUT_USD_PER_MILLION", "FAIRNESS_LIVE_MAX_COST_USD")
    for key in rates if selection["fairness"] else ():
        try:
            value = float(env.get(key, ""))
        except ValueError:
            raise ValueError(f"Invalid live release setting: {key}") from None
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid live release setting: {key}")
    return selection


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def assess_jobs(raw, selection=None):
    """Require selected jobs to pass and unselected jobs to remain skipped."""
    selection = complete_selection(selection)
    try:
        jobs = json.loads(raw)
    except (TypeError, ValueError):
        jobs = {}
    jobs = jobs if isinstance(jobs, dict) else {}
    checks = []
    for name in RELEASE_JOBS:
        job = jobs.get(name)
        result = job.get("result") if isinstance(job, dict) else None
        required = selection.get(name, True)
        checks.append({"check": "job:" + name, "passed": result == "success" if required else None,
                       "required": required, "result": result or "missing",
                       "status": ("PASS" if result == "success" else "FAIL / incomplete") if required else
                                 ("SKIPPED — not selected" if result == "skipped" else "FAIL / unexpected execution"),
                       "policy_satisfied": result == ("success" if required else "skipped")})
    return checks


def assess(directory, sha, *, agent_root=None, selection=None):
    selection = complete_selection(selection)
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
    for row in results:
        job = "live" if row["check"] in SUITES else "security-live" if row["check"] == "live-security" else "fairness"
        row["required"] = selection[job]
        if not row["required"]:
            row.update(passed=None, status="SKIPPED — not selected", policy_satisfied=True)
        else:
            row["status"] = "PASS" if row["passed"] else "FAIL / incomplete"
    return {"schema_version": 2, "release_sha": sha, "live_selection": selection,
            "passed": passed_checks(results), "live_evidence_complete": all(row["passed"] is True for row in results),
            "checks": results, "human_semantic_acceptance": "pending; automated contract gate only"}


def publish(report, directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Final release acceptance", "",
             f"Release: `{report['release_sha']}`. Automated result: **{'PASS' if report['passed'] else 'FAIL / incomplete'}**.",
             "Mandatory jobs and enabled live stages must pass or trigger rollback. Disabled live stages are SKIPPED and provide no live acceptance evidence. Human semantic/fairness review remains pending.",
             "", "| Check | Result |", "|---|---|"]
    lines += [f"| {row['check']} | {row.get('status', 'PASS' if row['passed'] else 'FAIL / incomplete')} |" for row in report["checks"]]
    lines += ["", "Live security exercises release source with real model calls and governed local corpora; agent/fairness suites exercise the deployed API/AWS.",
              "Available synthetic answers, paired diagnostics, usage and blinded review forms are retained in this artifact."]
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
        selection = validate_config(os.environ)
        if os.getenv("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.writelines(f"{job}={str(enabled).lower()}\n" for job, enabled in selection.items())
                output.write("live-selection=" + json.dumps(selection, separators=(",", ":")) + "\n")
    elif args.mode == "initialize":
        selection = parse_selection(os.getenv("RELEASE_LIVE_SELECTION"))
        for suite in SUITES:
            report = initial_report(suite)
            if not selection["live"]:
                report.update(status="SKIPPED", stage="not_selected", gate="not_selected")
            write_report(report, ROOT / "artifacts/agent-live" / suite)
        OUTPUT.mkdir(parents=True, exist_ok=True)
    else:
        try:
            selection = parse_selection(os.getenv("RELEASE_LIVE_SELECTION"))
            selection_check = {"check": "live-selection", "passed": True, "required": True, "status": "PASS"}
        except ValueError:
            selection = complete_selection(None)
            selection_check = {"check": "live-selection", "passed": False, "required": True,
                               "status": "FAIL / missing or invalid selection"}
        report = assess(OUTPUT, os.environ["RELEASE_SHA"], selection=selection)
        report["selection_valid"] = selection_check["passed"]
        if not report["selection_valid"]:
            report["live_selection"] = None
        report["checks"].append(selection_check)
        report["checks"].extend(assess_jobs(os.getenv("RELEASE_JOB_RESULTS"), selection))
        report["passed"] = passed_checks(report["checks"])
        publish(report, OUTPUT)
        if args.mode == "gate" and not report["passed"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
