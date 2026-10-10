"""Optional, bounded synthetic evaluations of the deployed API and AWS RAG.

This is a test client, not an alternative agent implementation. No production
configuration is changed. Provider failures remain failed evidence even when the
GitHub job is advisory. Only explicitly synthetic dialogue is retained.
"""
import argparse
import hashlib
import html
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

try:
    from . import investment_live_acceptance as investment
    from .live_evaluation import run_live_evaluation
except ImportError:
    import investment_live_acceptance as investment
    from live_evaluation import run_live_evaluation

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "infra/llmsecops/agent-live-evaluation-specs.json"
SUITES = ("orchestrator", "spending", "budget", "goal", "investment", "risk-compliance", "rag")


def initial_report(suite):
    specification = json.loads(SPEC_PATH.read_text())["suites"][suite]
    paths = [SPEC_PATH, investment.MANIFEST, *[ROOT / path for path in specification["datasets"]]]
    return {
        "schema_version": 1, "suite": suite, "mode": "live", "status": "NOT RUN",
        "stage": "awaiting_credentials", "specification": specification,
        "test_commit": os.getenv("GITHUB_SHA"), "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "started_at": datetime.now(UTC).isoformat(), "human_semantic_review": "pending",
        "dataset_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "records": [],
    }


def table_cell(value, limit=450):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return html.escape(text[:limit] + ("…" if len(text) > limit else "")).replace("|", "&#124;").replace("\n", "<br>")


def questions(report):
    """Render expected questions even when a provider call never completed."""
    suite = report["suite"]
    if suite == "rag":
        cases = investment.load_dataset(investment.RAG_CASES)
        for case in cases:
            row = next((r for r in report.get("records", []) if r.get("id") == case["id"]), None)
            yield case["query"], case["expected_source_ids"], row
    elif suite == "investment":
        for case in investment.load_dataset(investment.CASES):
            actual = next((r for r in report.get("records", []) if r.get("case_id") == case["id"]), {})
            for index, turn in enumerate(case["turns"]):
                rows = actual.get("turns", [])
                row = rows[index] if index < len(rows) else None
                yield turn["message"], turn["expected"], row
    else:
        for case in investment.load_dataset(ROOT / "infra/llmsecops/agent-live-evaluation-cases.jsonl"):
            if case["suite"] != suite:
                continue
            actual = next((r for r in report.get("records", []) if r.get("case_id") == case["id"]), {})
            rows = actual.get("turns", [])
            yield case["request"]["message"], case["expected"], rows[-1] if rows else None


def write_report(report, directory, *, publish=False):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    spec = report["specification"]
    lines = [f"## {report['suite']} live integration — {report['status']} (advisory)", "",
             f"- Stage: {report['stage']}; test SHA: {report.get('test_commit')}; deployed SHA: {report.get('deployed_commit', 'not verified')}.",
             "- Dataset: " + ", ".join(spec["datasets"]),
             "- Expected outputs: " + spec["expected_outputs"],
             "- Metrics: " + "; ".join(spec["metrics"]),
             "- Acceptance: " + " ".join(spec["acceptance_criteria"]),
             "- Measured: " + json.dumps(report.get("metrics", {})),
             "- Human semantic review is pending. Full answers, checks and AWS/model evidence are in the artifact.",
             "", "| Question | Expected | Result | Actual answer / retrieved passages |", "|---|---|---|---|"]
    for question, expected, actual in questions(report):
        status = "NOT RUN" if actual is None else "PASS" if actual.get("passed") else "FAIL"
        answer = "No response recorded" if actual is None else actual.get("answer", actual.get("results", "No response recorded"))
        lines.append("| " + " | ".join(map(table_cell, (question, expected, status, answer))) + " |")
    summary = "\n".join(lines) + "\n"
    (directory / "summary.md").write_text(summary)
    (directory / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Live agent evaluation</title>"
        "<style>body{max-width:1100px;margin:30px auto;font:16px system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
        f"<h1>{html.escape(report['suite'])}: {html.escape(report['status'])}</h1>"
        "<p>Optional evaluation; failure does not block deployment. Synthetic data only. Human review pending.</p>"
        "<pre>" + html.escape(json.dumps(report, indent=2, ensure_ascii=False)) + "</pre>")
    if publish and os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(summary)


def response_checks(build):
    def check(response, expected):
        audit = response.get("audit", {})
        calls = audit.get("model_calls", [])
        usage = (type(audit.get("model_call_count")) is int and audit["model_call_count"] == len(calls)
                 and audit.get("composition_usage_complete") is not False
                 and all(type(c.get(key)) is int and c[key] >= 0 for c in calls for key in ("input_tokens", "output_tokens"))
                 and all(audit.get("model_" + key) == sum(c.get(key) or 0 for c in calls)
                         for key in ("input_tokens", "output_tokens")))
        return [{"check": "deployed_build_matches", "passed": audit.get("build_commit") == build},
                {"check": "complete_consistent_usage", "passed": usage}]
    return check


def routing_metrics(cases, records):
    true_positive = false_positive = false_negative = exact = 0
    for case in cases:
        expected = set(case["expected"]["selected_agents"])
        record = next((item for item in records if item["case_id"] == case["id"]), {})
        turns = record.get("turns", [])
        actual = set(turns[-1].get("selected_agents", [])) if turns else set()
        exact += int(bool(turns) and actual == expected)
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return {"routing_accuracy": exact / len(cases), "routing_precision": precision,
            "routing_recall": recall, "routing_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "routing_tp": true_positive, "routing_fp": false_positive, "routing_fn": false_negative}


def execute(report, ecs, bedrock, environ):
    suite = report["suite"]
    services = {role: environ[role.upper() + "_SERVICE"] for role in ("ai", "backend", "frontend")}
    report["stage"] = "aws_preflight"
    report["aws_before"] = investment.capture_aws(ecs, environ["ECS_CLUSTER"], services)
    ai = report["aws_before"]["ai"]["config"]
    report["deployed_commit"] = ai["BUILD_COMMIT"]
    report["test_commit_matches_deployment"] = report.get("test_commit") == report["deployed_commit"]
    manifest = json.loads(investment.MANIFEST.read_text())
    if ai["EDUCATION_CORPUS_VERSION"] != manifest["corpus_version"]:
        raise ValueError("DEPLOYED_CORPUS_DIFFERS_FROM_TEST_MANIFEST")
    report["stage"] = "evaluating"
    if suite == "rag":
        cases = investment.load_dataset(investment.RAG_CASES)
        if len(cases) != report["specification"]["planned_cases"]:
            raise ValueError("DATASET_COUNT_MISMATCH")
        records = investment.bedrock_probe(bedrock, ai["EDUCATION_KNOWLEDGE_BASE_ID"], cases, manifest)
        for row in records:
            row["passed"] = bool(row["passed"] and row.get("aws_request_id"))
        report["records"] = records
        report["metrics"] = {"completed_queries": len(records), "planned_queries": 3,
                             "expected_source_hit_at_5": sum(r["expected_source_hit_at_5"] for r in records) / 3,
                             "passing_queries": sum(r["passed"] for r in records)}
        passed = len(records) == 3 and all(r["passed"] for r in records)
    elif suite == "investment":
        cases = investment.load_dataset(investment.CASES)
        if (len(cases) != report["specification"]["planned_cases"]
                or sum(len(case["turns"]) for case in cases) != report["specification"]["planned_turns"]):
            raise ValueError("DATASET_COUNT_MISMATCH")
        report["records"] = investment.run_conversations(
            environ["COACH_URL"], environ["SMOKE_BACKEND_API_KEY"], cases, manifest, ai["BUILD_COMMIT"])
        for row in report["records"]:
            for turn in row["turns"]:
                if not turn["expected"]["model_required"]:
                    continue
                proven = any(call.get("component") == "agent_investment_education"
                             and call.get("status") == "completed" and call.get("model_id") == investment.MODEL
                             and (call.get("input_tokens") or 0) > 0 and (call.get("output_tokens") or 0) > 0
                             for call in turn["model_calls"])
                turn["checks"].append({"check": "real_investment_specialist", "passed": proven})
                turn["passed"] = turn["passed"] and proven
            row["passed"] = row["passed"] and all(turn["passed"] for turn in row["turns"])
        turns = [turn for row in report["records"] for turn in row["turns"]]
        report["metrics"] = {"completed_turns": len(turns), "planned_turns": 7,
                             "passing_turns": sum(t["passed"] for t in turns),
                             "contract_pass_rate": sum(t["passed"] for t in turns) / 7,
                             "input_tokens": sum(t["audit"].get("model_input_tokens") or 0 for t in turns),
                             "output_tokens": sum(t["audit"].get("model_output_tokens") or 0 for t in turns)}
        passed = len(report["records"]) == len(cases) and len(turns) == 7 and all(r["passed"] for r in report["records"])
    else:
        cases = [case for case in investment.load_dataset(ROOT / "infra/llmsecops/agent-live-evaluation-cases.jsonl") if case["suite"] == suite]
        if len(cases) != report["specification"]["planned_cases"]:
            raise ValueError("DATASET_COUNT_MISMATCH")
        result = run_live_evaluation(
            url=environ["COACH_URL"], api_key=environ["SMOKE_BACKEND_API_KEY"], cases=cases,
            repeats=1, timeout_seconds=90, expected_model_provider="openai", expected_model_id=investment.MODEL,
            expected_prompt_version=json.loads((ROOT / "apps/ai-service/prompts/current/manifest.json").read_text())["version"],
            input_cost_per_million=0, output_cost_per_million=0, commit_sha=ai["BUILD_COMMIT"],
            maximum_total_tokens=75_000, capture_synthetic_dialogue=True, response_checks=response_checks(ai["BUILD_COMMIT"]))
        # Token budget is enforced; no price or credit-balance estimate is asserted.
        result.pop("cost_estimate")
        report["evaluation"] = result
        report["records"] = result.pop("records")
        report["metrics"] = {key: result[key] for key in ("total_runs", "requested_runs", "passed_runs", "pass_rate", "latency_ms", "token_usage", "token_usage_complete")}
        if suite == "orchestrator":
            report["metrics"].update(routing_metrics(cases, report["records"]))
        passed = (result["completed_requested_runs"] and not result["usage_unknown"]
                  and result["token_usage_complete"] and result["pass_rate"] == 1)
    report["stage"] = "aws_postflight"
    report["aws_after"] = investment.capture_aws(ecs, environ["ECS_CLUSTER"], services)
    report["deployment_unchanged"] = report["aws_before"] == report["aws_after"]
    report.update(status="PASS" if passed and report["deployment_unchanged"] else "FAIL", stage="complete")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=SUITES)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--summarize", action="store_true")
    args = parser.parse_args(argv)
    directory = ROOT / "artifacts/agent-live" / args.suite
    path = directory / "report.json"
    report = json.loads(path.read_text()) if path.exists() else initial_report(args.suite)
    if args.initialize or args.summarize:
        write_report(report, directory, publish=args.summarize)
        return 0
    if report["status"] != "NOT RUN":
        raise ValueError("REFUSE_TO_OVERWRITE_EVIDENCE")
    from botocore.exceptions import BotoCoreError, ClientError
    try:
        if os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch" or os.getenv("GITHUB_REF") != "refs/heads/main":
            raise ValueError("LIVE_REQUIRES_MANUAL_MAIN_DISPATCH")
        if os.getenv("GITHUB_RUN_ATTEMPT") != "1":
            raise ValueError("RERUN_REQUIRES_NEW_OPT_IN_DISPATCH")
        import boto3
        from botocore.config import Config
        config = Config(retries={"total_max_attempts": 1}, connect_timeout=10, read_timeout=30)
        region = os.environ["AWS_REGION"]
        execute(report, boto3.client("ecs", region_name=region, config=config),
                boto3.client("bedrock-agent-runtime", region_name=region, config=config), os.environ)
    except (BotoCoreError, ClientError, OSError, ValueError, KeyError, TypeError) as error:
        # Do not log exception text, HTTP bodies, headers, task envs or credentials.
        report.update(status="FAIL", error_type=type(error).__name__)
        if isinstance(error, ValueError) and re.fullmatch(r"[A-Z_]+", str(error)):
            report["error_code"] = str(error)
        if isinstance(error, ClientError):
            code = error.response.get("Error", {}).get("Code", "")
            if re.fullmatch(r"[A-Za-z_]+", code):
                report["aws_error_code"] = code
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        write_report(report, directory)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
