"""Compare rubric-scored synthetic runs and content-free traffic aggregates.

Run with ``python -m infra.scripts.model_drift --help``. No baseline is approved
automatically, and unknown/incomplete evidence never produces a passing gate.
"""

import argparse
import json
import math
import os
import re
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

POLICY_PATH = Path("infra/llmsecops/model-drift-policy.json")
METRICS = ("financial_correct", "grounded", "citations_supported", "safe", "helpful",
           "language_correct", "refusal_correct")
CODE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,180}$")
DIMENSIONS = {
    "input_language": {"en", "zh", "mixed", "other"},
    "input_length_band": {"short", "medium", "long"},
    "intent_bucket": {"analysis", "capture_budget", "capture_goal", "capture_spending"},
    "needs_input": {"true", "false"},
    "blocked": {"true", "false"},
}
AGENTS = ("budget", "spending", "goal_strategy", "investment_education", "risk_compliance")
QUERY = ('filter event = "coach.drift.observation" | stats count(*) as n by '
         'input_language, input_length_band, intent_bucket, agent_mix, needs_input, blocked '
         '| limit 10000')


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def number(value, minimum=0, maximum=None):
    if (type(value) not in {int, float} or not math.isfinite(value) or value < minimum
            or (maximum is not None and value > maximum)):
        raise ValueError("Invalid finite numeric evidence")
    return value


def code(value):
    if not isinstance(value, str) or not CODE.fullmatch(value):
        raise ValueError("Invalid metadata identifier")
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps must include a timezone")
    return parsed.astimezone(UTC)


def load_policy(path=POLICY_PATH):
    policy = load(path)
    if policy.get("version") != 3 or set(policy["metrics"]) != {"structural_pass", *METRICS}:
        raise ValueError("Unsupported drift policy")
    if policy.get("evaluation_mode") not in {"same_model", "separate_model"}:
        raise ValueError("Unsupported evaluator mode")
    if set(policy.get("operational", {})) != {"maximum_p95_ms"}:
        raise ValueError("Missing operational latency policy")
    number(policy["operational"]["maximum_p95_ms"], 1)
    for key in ("minimum_samples", "confirmation_runs", "maximum_gap_days"):
        if type(policy[key]) is not int or policy[key] < 1:
            raise ValueError("Invalid sampling/confirmation policy")
    for rule in policy["metrics"].values():
        number(rule["minimum"], 0, 1)
        number(rule["allowed_drop"], 0, 1)
    number(policy["calibration_agreement"], 0, 1)
    for key, allowed in (("required_specialists", set(AGENTS)), ("required_languages", {"en", "zh"}),
                         ("required_metrics", set(METRICS))):
        if not policy[key] or not set(policy[key]) <= allowed or len(set(policy[key])) != len(policy[key]):
            raise ValueError("Invalid required benchmark coverage")
    for key in ("current_days", "reference_days", "minimum_samples", "minimum_cell_count"):
        if type(policy["inputs"][key]) is not int or policy["inputs"][key] < 1:
            raise ValueError("Invalid input aggregation policy")
    number(policy["inputs"]["maximum_js_divergence"], 0, 1)
    return policy


def validate_capture(capture):
    allowed = {"schema_version", "measurement", "run_id", "generated_at", "commit_sha", "identity",
               "expected_samples", "samples", "complete", "operational_pass", "operational_failures",
               "latency_ms", "generator_token_usage", "generator_cost_estimate", "evaluator_usage", "evidence_sha256"}
    if set(capture) - allowed:
        raise ValueError("Unapproved fields in quality evidence")
    if capture.get("schema_version") != 1 or capture.get("measurement") != "live_quality_capture":
        raise ValueError("Expected live rubric-scored evidence")
    code(capture["run_id"])
    timestamp(capture["generated_at"])
    if not capture.get("identity") or capture["identity"].get("model_provider") == "local_fixture":
        raise ValueError("A fixture cannot establish live model quality")
    identity = capture["identity"]
    strings = {"model_provider", "model_id", "prompt_set_version", "prompt_content_hash", "dataset_sha256",
               "evaluator_model", "evaluator_response_model", "evaluator_prompt_sha256", "evaluator_schema_sha256",
               "evaluator_reasoning_effort", "build_commit", "target_host", "evaluation_mode"}
    if set(identity) != strings | {"roles", "corpus_versions", "evaluator_max_output_tokens",
                                    "generator_price_assumptions", "generator_budget_usd", "maximum_p95_ms"}:
        raise ValueError("Incomplete or unapproved identity fields")
    for field in strings:
        code(identity[field])
    if identity["evaluation_mode"] not in {"same_model", "separate_model"}:
        raise ValueError("Unsupported evaluator mode")
    number(identity["evaluator_max_output_tokens"], 1)
    number(identity["generator_budget_usd"], 0.000001)
    number(identity["maximum_p95_ms"], 1)
    number(capture["latency_ms"]["p95"], 0)
    if capture.get("operational_pass") is True and capture["latency_ms"]["p95"] > identity["maximum_p95_ms"]:
        raise ValueError("Operational acceptance contradicts measured latency")
    if len(identity["generator_price_assumptions"]) != 2:
        raise ValueError("Invalid price assumptions")
    for rate in identity["generator_price_assumptions"]:
        number(rate, 0.000001)
    if not identity["roles"] or set(identity["corpus_versions"]) != {"education", "policy"}:
        raise ValueError("Missing role or corpus identity")
    for version in identity["corpus_versions"].values():
        code(version)
    for component, role in identity["roles"].items():
        code(component)
        if set(role) != {"model_id", "provider_model_id", "reasoning_effort", "max_output_tokens"}:
            raise ValueError("Incomplete role identity")
        for field in ("model_id", "provider_model_id", "reasoning_effort"):
            code(role[field])
        number(role["max_output_tokens"], 1)
        matches = (role["model_id"] == identity["evaluator_model"],
                   role["provider_model_id"] == identity["evaluator_response_model"])
        if identity["evaluation_mode"] == "separate_model" and any(matches):
            raise ValueError("Evaluator is not independent of generation")
        if identity["evaluation_mode"] == "same_model" and (not all(matches)
                or identity["evaluator_model"] != identity["model_id"]):
            raise ValueError("Same-model evaluation requires matching generator and evaluator models")
    if capture.get("evidence_sha256") != digest({k: v for k, v in capture.items() if k != "evidence_sha256"}):
        raise ValueError("Quality evidence checksum mismatch")
    expected = capture["expected_samples"]
    if not expected or len({code(item["sample_id"]) for item in expected}) != len(expected):
        raise ValueError("Invalid expected sample inventory")
    inventory = {item["sample_id"]: item for item in expected}
    seen = set()
    for sample in capture["samples"]:
        if set(sample) - {"sample_id", "case_id", "specialist", "language", "intent", "structural_pass",
                          "scores", "trace_id", "error_code"}:
            raise ValueError("Unapproved fields in quality sample")
        sample_id = code(sample["sample_id"])
        if sample_id in seen or sample_id not in inventory:
            raise ValueError("Duplicate or unexpected quality sample")
        seen.add(sample_id)
        for key in ("specialist", "language", "intent"):
            if sample[key] != inventory[sample_id][key]:
                raise ValueError("Sample subgroup differs from dataset")
            code(sample[key])
        if type(sample["structural_pass"]) is not bool:
            raise ValueError("Missing structural result")
        required = inventory[sample_id]["metrics"]
        if not required or not set(required) <= set(METRICS) or "safe" not in required:
            raise ValueError("Invalid required quality metrics")
        if sample.get("scores") is not None and (set(sample["scores"]) != set(required)
                or any(type(v) is not bool for v in sample["scores"].values())):
            raise ValueError("Incomplete or nonboolean quality scores")
    return inventory


def complete(capture):
    return (capture.get("complete") is True and len(capture["samples"]) == len(capture["expected_samples"])
            and all(sample.get("scores") is not None for sample in capture["samples"]))


def wilson(passed, count):
    if not count:
        return None
    z = 1.96
    proportion = passed / count
    denominator = 1 + z * z / count
    center = (proportion + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(proportion * (1 - proportion) / count + z * z / (4 * count * count)) / denominator
    return [round(max(0, center - radius), 6), round(min(1, center + radius), 6)]


def metrics(capture):
    bins = defaultdict(list)
    for sample in capture["samples"]:
        groups = ["all", *(key + ":" + sample[key] for key in ("specialist", "language", "intent"))]
        for group in groups:
            bins[(group, "structural_pass")].append(sample["structural_pass"])
            for metric, score in (sample.get("scores") or {}).items():
                bins[(group, metric)].append(score)
    return {group + "/" + metric: {"score": sum(scores) / len(scores), "passed": sum(scores),
            "count": len(scores), "interval_95": wilson(sum(scores), len(scores))}
            for (group, metric), scores in sorted(bins.items())}


def approve_baseline(capture, reviews, policy, approval_reference):
    validate_capture(capture)
    if not complete(capture) or capture.get("operational_pass") is not True:
        raise ValueError("Baseline needs complete quality and operational acceptance")
    if capture["identity"]["maximum_p95_ms"] != policy["operational"]["maximum_p95_ms"]:
        raise ValueError("Captured latency limit differs from the approval policy")
    if capture["identity"]["evaluation_mode"] != policy["evaluation_mode"]:
        raise ValueError("Captured evaluator mode differs from the approval policy")
    for field, required in (("specialist", policy["required_specialists"]), ("language", policy["required_languages"])):
        if not set(required) <= {sample[field] for sample in capture["samples"]}:
            raise ValueError("Baseline is missing a required benchmark subgroup")
    if not {"all/" + metric for metric in policy["required_metrics"]} <= set(metrics(capture)):
        raise ValueError("Baseline is missing a required quality metric")
    code(approval_reference)
    human = {}
    for review in reviews:
        if set(review) != {"sample_id", "scores"} or review["sample_id"] in human:
            raise ValueError("Human review must have unique sample IDs and coded scores only")
        human[review["sample_id"]] = review["scores"]
    if set(human) != {sample["sample_id"] for sample in capture["samples"]}:
        raise ValueError("Human calibration must cover every captured sample")
    agreements = defaultdict(list)
    for sample in capture["samples"]:
        scores = human[sample["sample_id"]]
        if set(scores) != set(sample["scores"]) or any(type(v) is not bool for v in scores.values()):
            raise ValueError("Invalid human calibration scores")
        for metric, score in scores.items():
            agreements[metric].append(score == sample["scores"][metric])
            if policy["metrics"][metric].get("critical") and (not score or not sample["scores"][metric]):
                raise ValueError("Critical human or judge failure prevents baseline approval")
    if any(sum(values) / len(values) < policy["calibration_agreement"] for values in agreements.values()):
        raise ValueError("Evaluator disagrees with human calibration")
    human_capture = {**capture, "samples": [{**sample, "scores": human[sample["sample_id"]]}
                                           for sample in capture["samples"]]}
    for report in (metrics(capture), metrics(human_capture)):
        if any(item["count"] < policy["minimum_samples"]
               or item["score"] < policy["metrics"][key.rsplit("/", 1)[1]]["minimum"]
               for key, item in report.items()):
            raise ValueError("Baseline fails sample coverage or absolute acceptance")
    return {"schema_version": 1, "baseline_id": "baseline-" + digest(capture)[:16],
            "approved_at": datetime.now(UTC).isoformat(), "approval_reference": approval_reference,
            "policy_sha256": digest(policy), "human_review_sha256": digest(reviews),
            "calibration_agreement": {key: sum(values) / len(values) for key, values in agreements.items()},
            "capture": capture}


def js_divergence(reference, current):
    keys = set(reference) | set(current)
    ref_total, cur_total = sum(reference.values()), sum(current.values())
    if not ref_total or not cur_total:
        raise ValueError("Empty distribution")
    result = 0.0
    for key in keys:
        p, q = reference.get(key, 0) / ref_total, current.get(key, 0) / cur_total
        midpoint = (p + q) / 2
        result += (p * math.log2(p / midpoint) if p else 0) / 2
        result += (q * math.log2(q / midpoint) if q else 0) / 2
    return max(0.0, min(1.0, result))


def input_checks(evidence, policy):
    if evidence.get("schema_version") != 1 or evidence.get("measurement") != "input_aggregates":
        raise ValueError("Unsupported aggregate evidence")
    reference, current = evidence["reference"], evidence["current"]
    if (timestamp(reference["end"]) != timestamp(current["start"])
            or timestamp(reference["start"]) >= timestamp(reference["end"])
            or timestamp(current["start"]) >= timestamp(current["end"])
            or reference["environment"] != current["environment"]
            or reference.get("configuration_sha256") != current.get("configuration_sha256")):
        raise ValueError("Input windows must be consecutive, non-overlapping and from one environment")
    for window, days in ((reference, policy["reference_days"]), (current, policy["current_days"])):
        if timestamp(window["end"]) - timestamp(window["start"]) != timedelta(days=days):
            raise ValueError("Input window duration differs from policy")
        totals = {sum(values.values()) for values in window["counts"].values()}
        if len(totals) != 1 or set(window["counts"]) != {*DIMENSIONS, "agent_mix"}:
            raise ValueError("Aggregate dimensions must cover the same observation population")
    results = {}
    for dimension in (*DIMENSIONS, "agent_mix"):
        distributions = []
        for window in (reference, current):
            distribution = window["counts"][dimension]
            for key, count in distribution.items():
                if (dimension == "agent_mix" and key != "none"
                        and (len(key.split(".")) != len(set(key.split("."))) or not set(key.split(".")) <= set(AGENTS))):
                    raise ValueError("Invalid agent aggregate bucket")
                if dimension in DIMENSIONS and key not in DIMENSIONS[dimension]:
                    raise ValueError("Invalid aggregate bucket")
                if type(count) is not int or count < 0:
                    raise ValueError("Invalid aggregate count")
            distributions.append(distribution)
        reference_counts, current_counts = distributions
        ref_count, cur_count = sum(reference_counts.values()), sum(current_counts.values())
        suppressed = {key for key in set(reference_counts) | set(current_counts)
                      if 0 < reference_counts.get(key, 0) < policy["minimum_cell_count"]
                      or 0 < current_counts.get(key, 0) < policy["minimum_cell_count"]}
        def collapse(counts, suppressed=suppressed):
            return {**{key: value for key, value in counts.items() if key not in suppressed},
                    "other_suppressed": sum(value for key, value in counts.items() if key in suppressed)}
        eligible = min(ref_count, cur_count) >= policy["minimum_samples"]
        distance = js_divergence(collapse(reference_counts), collapse(current_counts)) if eligible else None
        results["inputs/" + dimension] = {
            "count": cur_count, "reference_count": ref_count, "js_divergence": distance,
            "threshold": policy["maximum_js_divergence"], "eligible": eligible,
            "relative_breach": eligible and distance > policy["maximum_js_divergence"],
        }
    return results


def compare(capture, baseline, policy, previous=None, inputs=None, now=None):
    validate_capture(capture)
    now = now or datetime.now(UTC)
    current_metrics = metrics(capture)
    report = {"schema_version": 1, "run_id": capture["run_id"], "generated_at": capture["generated_at"],
              "baseline_id": baseline.get("baseline_id") if baseline else None,
              "policy_sha256": digest(policy), "identity_sha256": digest(capture["identity"]),
              "evaluation_mode": capture["identity"]["evaluation_mode"],
              "evidence_sha256": capture["evidence_sha256"], "status": "pass", "passed": False,
              "checks": {}, "failed_case_ids": sorted({code(sample["case_id"]) for sample in capture["samples"]
                  if sample.get("scores") is None or not sample["structural_pass"] or not all(sample["scores"].values())}),
              "operational_pass": capture.get("operational_pass") is True}
    incomplete = not complete(capture)
    absolute_failure = not report["operational_pass"]
    critical = any(sample.get("scores", {}).get("safe") is False if sample.get("scores") is not None else False
                   for sample in capture["samples"])
    critical |= any(sample.get("intent") == "safety" and not sample["structural_pass"] for sample in capture["samples"])
    config_changed = capture["identity"]["maximum_p95_ms"] != policy["operational"]["maximum_p95_ms"]
    config_changed |= capture["identity"]["evaluation_mode"] != policy["evaluation_mode"]
    reference_metrics = {}
    if baseline:
        validate_capture(baseline["capture"])
        if (baseline.get("baseline_id") != "baseline-" + digest(baseline["capture"])[:16]
                or baseline.get("capture", {}).get("operational_pass") is not True):
            raise ValueError("Baseline identity or acceptance is invalid")
        if not baseline.get("approval_reference") or not baseline.get("human_review_sha256") or not complete(baseline["capture"]):
            raise ValueError("Baseline is not reviewed and complete")
        if baseline["policy_sha256"] != digest(policy):
            config_changed = True
        config_changed |= baseline["capture"]["identity"] != capture["identity"]
        config_changed |= baseline["capture"]["expected_samples"] != capture["expected_samples"]
        reference_metrics = metrics(baseline["capture"])
    eligible_previous = bool(previous and baseline and not config_changed
        and previous.get("schema_version") == 1 and previous.get("baseline_id") == report["baseline_id"]
        and previous.get("policy_sha256") == report["policy_sha256"]
        and previous.get("identity_sha256") == report["identity_sha256"]
        and previous.get("status") in {"pass", "warning", "drift"}
        and previous.get("run_id") != report["run_id"]
        and previous.get("evidence_sha256") != report["evidence_sha256"]
        and timestamp(previous["generated_at"]) < timestamp(report["generated_at"])
        and timedelta(0) <= now - timestamp(previous["generated_at"]) <= timedelta(days=policy["maximum_gap_days"]))
    for key, result in current_metrics.items():
        metric = key.rsplit("/", 1)[1]
        rule = policy["metrics"][metric]
        reference = reference_metrics.get(key)
        eligible = result["count"] >= policy["minimum_samples"]
        absolute = result["score"] < rule["minimum"]
        critical |= bool(rule.get("critical") and result["passed"] < result["count"])
        relative = bool(reference and not config_changed and eligible
                        and reference["score"] - result["score"] > rule["allowed_drop"] + 1e-12)
        report["checks"][key] = {**result, "baseline": reference["score"] if reference else None,
            "minimum": rule["minimum"], "allowed_drop": rule["allowed_drop"],
            "eligible": eligible, "absolute_breach": absolute, "relative_breach": relative}
        incomplete |= not eligible
        absolute_failure |= absolute
    if inputs is not None:
        report["input_windows"] = {key: {field: code(window[field]) if field == "environment" else window[field]
                                  for field in ("start", "end", "environment")} for key, window in inputs.items()
                                  if key in {"reference", "current"}}
        report["checks"].update(input_checks(inputs, policy["inputs"]))
        incomplete |= any(not item["eligible"] for item in report["checks"].values())
    relative_breach = confirmed = False
    for key, check in report["checks"].items():
        streak = 0
        if check["relative_breach"]:
            old = previous.get("checks", {}).get(key, {}) if eligible_previous else {}
            old_count = old.get("consecutive_breaches", 0) if old.get("relative_breach") else 0
            streak = min(old_count + 1, policy["confirmation_runs"]) if type(old_count) is int else 1
            relative_breach = True
        check["consecutive_breaches"] = streak
        confirmed |= streak >= policy["confirmation_runs"]
    report["status"] = ("critical" if critical else "acceptance_failed" if absolute_failure else
        "incomplete" if incomplete else "baseline_required" if not baseline else
        "configuration_changed" if config_changed else "drift" if confirmed else
        "warning" if relative_breach else "pass")
    report["passed"] = report["status"] in {"pass", "warning"}
    report["inputs_status"] = "evaluated" if inputs is not None else "not_requested"
    return report


def collect_window(client, log_group, start, end, identity=None):
    query = QUERY
    if identity:
        prefix = (f'filter model_id = "{code(identity["model_id"])}" and '
                  f'prompt_content_hash = "{code(identity["prompt_content_hash"])}" and '
                  f'build_commit = "{code(identity["build_commit"])}" | ')
        query = prefix + query
    query_id = client.start_query(logGroupName=log_group, startTime=int(start.timestamp()),
                                  endTime=int(end.timestamp()), queryString=query)["queryId"]
    deadline = time.monotonic() + 55
    try:
        while time.monotonic() < deadline:
            result = client.get_query_results(queryId=query_id)
            if result["status"] == "Complete":
                rows = result["results"]
                if len(rows) >= 10000:
                    raise ValueError("Aggregate query may be truncated")
                counts = {dimension: defaultdict(int) for dimension in (*DIMENSIONS, "agent_mix")}
                for row in rows:
                    fields = {item["field"]: item["value"] for item in row}
                    count = int(fields["n"])
                    if count < 1:
                        raise ValueError("Invalid CloudWatch aggregate")
                    for dimension, values in counts.items():
                        values[fields[dimension]] += count
                return {"start": start.isoformat(), "end": end.isoformat(), "environment": code(log_group),
                        "configuration_sha256": digest(identity) if identity else None,
                        "counts": {dimension: dict(values) for dimension, values in counts.items()}}
            if result["status"] not in {"Scheduled", "Running"}:
                raise ValueError("Aggregate query failed")
            time.sleep(1)
        raise TimeoutError("Aggregate query timed out")
    finally:
        client.stop_query(queryId=query_id)


def collect_inputs(client, log_group, policy, now=None, identity=None):
    groups = client.describe_log_groups(logGroupNamePrefix=log_group).get("logGroups", [])
    exact = [group for group in groups if group.get("logGroupName") == log_group]
    if len(exact) != 1 or (exact[0].get("retentionInDays") is not None
            and exact[0]["retentionInDays"] < policy["current_days"] + policy["reference_days"]):
        raise ValueError("Log retention cannot cover the configured comparison windows")
    end = (now or datetime.now(UTC)).astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=policy["current_days"])
    reference_start = start - timedelta(days=policy["reference_days"])
    return {"schema_version": 1, "measurement": "input_aggregates",
            "reference": collect_window(client, log_group, reference_start, start, identity),
            "current": collect_window(client, log_group, start, end, identity)}


def summary(report):
    lines = ["## Model drift", "", f"- Result: **{report['status']}**",
             f"- Evaluator mode: {report.get('evaluation_mode', 'unavailable')}",
             f"- Baseline: {report['baseline_id'] or 'required'}",
             f"- Input comparison: {report['inputs_status']}", "",
             "| Metric/subgroup | Current | Baseline | Count | Consecutive breaches |",
             "|---|---:|---:|---:|---:|"]
    for key, check in report["checks"].items():
        lines.append(f"| {key} | {check.get('score', check.get('js_divergence'))} | "
                     f"{check.get('baseline', check.get('threshold'))} | {check['count']} | {check['consecutive_breaches']} |")
    return "\n".join(lines) + "\n"


def notify(report, client, topic):
    if report["status"] in {"pass", "warning"}:
        return False
    if not re.fullmatch(r"arn:[a-z0-9-]+:sns:[a-z0-9-]+:[0-9]{12}:[A-Za-z0-9_-]+", topic):
        raise ValueError("Invalid SNS topic")
    # Never publish provider text, capture payloads or arbitrary external report fields.
    input_only = (report["status"] == "drift" and all(key.startswith("inputs/")
                  for key, item in report["checks"].items() if item.get("relative_breach")))
    message = {"status": code(report["status"]), "severity": "P1" if report["status"] == "critical" else "P3" if input_only else "P2",
               "run_id": code(report["run_id"]), "baseline_id": code(report["baseline_id"]) if report["baseline_id"] else None,
               "policy_sha256": code(report["policy_sha256"]),
               "failed_case_ids": [code(value) for value in report["failed_case_ids"]],
               "owner": "Team-9-operations", "runbook": "docs/operational-alert-runbook.md#drift-response",
               "breached_checks": [{"metric": code(key), "count": item["count"],
                   "actual": item.get("score", item.get("js_divergence")),
                   "threshold": item.get("minimum", item.get("threshold")),
                   "consecutive_breaches": item["consecutive_breaches"]}
                   for key, item in report["checks"].items()
                   if item.get("absolute_breach") or item.get("relative_breach")]}
    client.publish(TopicArn=topic, Subject="Financial coach model drift: " + report["status"],
                   Message=json.dumps(message, allow_nan=False))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    commands = parser.add_subparsers(dest="command", required=True)
    baseline_parser = commands.add_parser("approve-baseline")
    baseline_parser.add_argument("--capture", required=True, type=Path)
    baseline_parser.add_argument("--human-reviews", required=True, type=Path)
    baseline_parser.add_argument("--approval-reference", required=True)
    baseline_parser.add_argument("--output", required=True, type=Path)
    comparison = commands.add_parser("compare")
    comparison.add_argument("--capture", required=True, type=Path)
    comparison.add_argument("--baseline", type=Path)
    comparison.add_argument("--previous", type=Path)
    comparison.add_argument("--inputs", type=Path)
    comparison.add_argument("--input-log-group")
    comparison.add_argument("--sns-topic-arn")
    comparison.add_argument("--history-required", action="store_true", help="Fail closed if workflow history restoration failed")
    comparison.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    policy = load_policy(args.policy)
    try:
        if args.command == "approve-baseline":
            if args.output.exists():
                raise ValueError("Refusing to overwrite an existing baseline")
            write(args.output, approve_baseline(load(args.capture), load(args.human_reviews), policy, args.approval_reference))
            return
        inputs = load(args.inputs) if args.inputs else None
        if args.history_required and (args.previous is None or not args.previous.exists()):
            raise ValueError("Comparison history was not restored")
        if args.input_log_group:
            if inputs is not None:
                raise ValueError("Choose a file or a live aggregate source")
            import boto3

            inputs = collect_inputs(boto3.client("logs"), args.input_log_group, policy["inputs"],
                                    identity=load(args.capture)["identity"])
        report = compare(load(args.capture), load(args.baseline) if args.baseline else None, policy,
                         load(args.previous) if args.previous and args.previous.exists() else None, inputs)
    except Exception:  # noqa: BLE001 - always retain a content-free failure report, including AWS errors.
        if args.command == "approve-baseline":
            raise SystemExit("Baseline approval failed: invalid, incomplete or unacceptable evidence") from None
        report = {"schema_version": 1, "run_id": "error-" + uuid4().hex,
                  "generated_at": datetime.now(UTC).isoformat(), "baseline_id": None,
                  "policy_sha256": digest(policy), "status": "incomplete", "passed": False,
                  "checks": {}, "failed_case_ids": [], "inputs_status": "unavailable"}
    write(args.output, report)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as handle:
            handle.write(summary(report))
    if args.sns_topic_arn:
        import boto3

        notify(report, boto3.client("sns"), args.sns_topic_arn)
    print(f"Model drift: {report['status']}")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
