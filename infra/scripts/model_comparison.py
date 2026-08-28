import argparse
import csv
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MODEL_ROLES = {"baseline", "candidate"}
REQUIRED_MODEL_FIELDS = {
    "role",
    "name",
    "model_id",
    "foundation_model_id",
    "aws_region",
    "invocation_type",
    "geography",
    "deployment_source_regions",
    "input_cost_per_million",
    "output_cost_per_million",
    "availability_source",
    "pricing_source",
    "pricing_checked_on",
}


def _safe_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        candidate = str(response.get("Error", {}).get("Code", ""))
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate):
            return candidate.upper()
    candidate = str(getattr(exc, "code", ""))
    if re.fullmatch(r"[A-Z0-9_-]{1,128}", candidate):
        return candidate
    return type(exc).__name__.upper()


def _require_https(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.startswith("https://"):
        raise ValueError(f"{field} must be an HTTPS URL")


def load_policy(path: Path) -> dict[str, Any]:
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != 1:
        raise ValueError("model comparison policy schema_version must be 1")
    if not policy.get("comparison_id") or not policy.get("cases"):
        raise ValueError("model comparison policy requires comparison_id and cases")
    if int(policy.get("repeats", 0)) not in range(1, 6):
        raise ValueError("model comparison repeats must be between 1 and 5")

    selection = policy.get("selection", {})
    if not selection.get("required_deployment_region"):
        raise ValueError("selection requires a deployment Region")
    if not selection.get("required_geography"):
        raise ValueError("selection requires a geography")
    if not 0 <= float(selection.get("minimum_pass_rate", -1)) <= 1:
        raise ValueError("minimum_pass_rate must be between zero and one")
    if float(selection.get("maximum_p95_ms", 0)) <= 0:
        raise ValueError("maximum_p95_ms must be positive")
    if float(selection.get("maximum_estimated_cost_usd", -1)) < 0:
        raise ValueError("maximum_estimated_cost_usd must not be negative")

    models = policy.get("models", [])
    roles = [model.get("role") for model in models]
    if roles.count("baseline") != 1 or roles.count("candidate") < 1:
        raise ValueError("policy requires one baseline and at least one candidate")
    if any(role not in MODEL_ROLES for role in roles):
        raise ValueError("model roles must be baseline or candidate")
    model_ids = [model.get("model_id") for model in models]
    if len(model_ids) != len(set(model_ids)):
        raise ValueError("model IDs must be unique")

    for model in models:
        missing = REQUIRED_MODEL_FIELDS - set(model)
        if missing:
            raise ValueError(f"model entry is missing fields: {sorted(missing)}")
        if model["invocation_type"] not in {"geo_inference_profile", "in_region"}:
            raise ValueError("unsupported model invocation_type")
        if not model["deployment_source_regions"]:
            raise ValueError("deployment_source_regions must not be empty")
        if float(model["input_cost_per_million"]) < 0:
            raise ValueError("input token price must not be negative")
        if float(model["output_cost_per_million"]) < 0:
            raise ValueError("output token price must not be negative")
        _require_https(model["availability_source"], "availability_source")
        _require_https(model["pricing_source"], "pricing_source")
        datetime.fromisoformat(model["pricing_checked_on"])
    return policy


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            case = json.loads(line)
            if not case.get("id") or not case.get("category"):
                raise ValueError(f"invalid comparison case at line {line_number}")
            if case.get("kind") == "fairness_pair":
                if len(case.get("requests", [])) != 2 or not case.get("compare"):
                    raise ValueError(
                        f"fairness case at line {line_number} requires two requests and compare"
                    )
            elif not case.get("request") or "expected" not in case:
                raise ValueError(
                    f"comparison case at line {line_number} requires request and expected"
                )
            cases.append(case)
    if not cases:
        raise ValueError("model comparison case set is empty")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("model comparison case IDs must be unique")
    return cases


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(len(ordered) * percentile) - 1, 0)
    return round(ordered[index], 2)


def inspect_catalog(model: dict[str, Any]) -> dict[str, Any]:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client("bedrock", region_name=model["aws_region"])
    try:
        if model["invocation_type"] == "geo_inference_profile":
            response = client.get_inference_profile(
                inferenceProfileIdentifier=model["model_id"]
            )
            destinations = sorted(
                {
                    item["modelArn"].split(":")[3]
                    for item in response.get("models", [])
                    if item.get("modelArn")
                }
            )
            return {
                "verified": response.get("status") == "ACTIVE",
                "catalog_type": "inference_profile",
                "status": response.get("status"),
                "profile_arn": response.get("inferenceProfileArn"),
                "destination_regions": destinations,
            }

        response = client.get_foundation_model(
            modelIdentifier=model["foundation_model_id"]
        )
        details = response.get("modelDetails", {})
        lifecycle = details.get("modelLifecycle", {})
        return {
            "verified": lifecycle.get("status") == "ACTIVE",
            "catalog_type": "foundation_model",
            "status": lifecycle.get("status"),
            "model_arn": details.get("modelArn"),
            "input_modalities": details.get("inputModalities", []),
            "output_modalities": details.get("outputModalities", []),
            "inference_types": details.get("inferenceTypesSupported", []),
            "destination_regions": [model["aws_region"]],
        }
    except (BotoCoreError, ClientError) as exc:
        return {
            "verified": False,
            "catalog_type": model["invocation_type"],
            "error_code": _safe_error_code(exc),
            "destination_regions": [],
        }


def _audit_totals(responses: list[Any]) -> tuple[int, int, int]:
    input_tokens = sum(
        int(response.audit.get("model_input_tokens") or 0) for response in responses
    )
    output_tokens = sum(
        int(response.audit.get("model_output_tokens") or 0) for response in responses
    )
    model_calls = sum(int(response.audit.get("model_call_count") or 0) for response in responses)
    return input_tokens, output_tokens, model_calls


def _review_evidence(responses: list[Any]) -> dict[str, Any]:
    return {
        "answers": [response.answer for response in responses],
        "agent_results": [
            {
                "agent": result.agent.value,
                "summary": result.summary,
                "rationale": result.rationale,
                "confidence": result.confidence,
                "blocked": result.blocked,
            }
            for response in responses
            for result in response.agent_results
        ],
        "source_ids": sorted(
            {
                source.source_id
                for response in responses
                for source in response.sources
            }
        ),
        "disclaimers": sorted(
            {
                disclaimer
                for response in responses
                for disclaimer in response.disclaimers
            }
        ),
    }


def _execute_case(orchestrator: Any, case: dict[str, Any]) -> tuple[dict, dict]:
    from app.core.schemas import CoachRequest
    from app.evals.runner import _fairness_projection

    from infra.scripts.live_evaluation import evaluate_response

    responses = []
    request_latencies_ms = []
    if case.get("kind") == "fairness_pair":
        requests = []
        for item in case["requests"]:
            payload = json.loads(json.dumps(item))
            payload["session_id"] = f"{payload['session_id']}-{uuid4().hex[:8]}"
            requests.append(CoachRequest(**payload))
        for request in requests:
            request_started = time.perf_counter()
            responses.append(orchestrator.handle(request))
            request_latencies_ms.append(
                round((time.perf_counter() - request_started) * 1000, 2)
            )
        checks = [
            {
                "check": f"fairness_{field}",
                "passed": _fairness_projection(responses[0], field)
                == _fairness_projection(responses[1], field),
            }
            for field in case["compare"]
        ]
        for response in responses:
            checks.extend(
                [
                    {
                        "check": "model_provider",
                        "passed": response.audit.get("model_provider") == "bedrock",
                    },
                    {
                        "check": "model_id",
                        "passed": response.audit.get("model_id")
                        == orchestrator.config.model_id,
                    },
                    {
                        "check": "prompt_set_version",
                        "passed": response.audit.get("prompt_set_version")
                        == orchestrator.config.prompt_set_version,
                    },
                ]
            )
    else:
        payload = json.loads(json.dumps(case["request"]))
        payload["session_id"] = f"{payload['session_id']}-{uuid4().hex[:8]}"
        request_started = time.perf_counter()
        response = orchestrator.handle(CoachRequest(**payload))
        request_latencies_ms.append(
            round((time.perf_counter() - request_started) * 1000, 2)
        )
        responses = [response]
        passed, checks = evaluate_response(
            response.model_dump(mode="json"),
            case["expected"],
            expected_model_provider="bedrock",
            expected_model_id=orchestrator.config.model_id,
            expected_prompt_version=orchestrator.config.prompt_set_version,
        )
        if passed != all(check["passed"] for check in checks):
            raise AssertionError("response check aggregation was inconsistent")

    input_tokens, output_tokens, model_calls = _audit_totals(responses)
    record = {
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
        "latency_ms": max(request_latencies_ms),
        "request_latencies_ms": request_latencies_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model_call_count": model_calls,
    }
    review = _review_evidence(responses)
    review["messages"] = (
        [item["message"] for item in case["requests"]]
        if case.get("kind") == "fairness_pair"
        else [case["request"]["message"]]
    )
    return record, review


def run_model(
    model: dict[str, Any],
    cases: list[dict[str, Any]],
    repeats: int,
    prompt_set_version: str,
    commit_sha: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from app.core.config import Settings
    from app.orchestrator import AgentOrchestrator

    config = Settings(
        APP_ENV="test",
        MODEL_PROVIDER="bedrock",
        MODEL_ID=model["model_id"],
        AWS_REGION=model["aws_region"],
        RAG_PROVIDER="local_fixture",
        PROMPT_SET_VERSION=prompt_set_version,
        AI_SERVICE_API_KEY="synthetic-model-comparison-only",
        MODEL_READ_TIMEOUT_SECONDS=30,
        AGENT_TIMEOUT_SECONDS=45,
    )
    orchestrator = AgentOrchestrator(config=config)
    records = []
    review_items = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_model_calls = 0

    for repeat in range(1, repeats + 1):
        for case in cases:
            base_record = {
                "case_id": case["id"],
                "category": case["category"],
                "repeat": repeat,
            }
            started = time.perf_counter()
            try:
                result, review = _execute_case(orchestrator, case)
                base_record.update(result)
                review_items.append(
                    {
                        "model_id": model["model_id"],
                        "case_id": case["id"],
                        "category": case["category"],
                        "repeat": repeat,
                        **review,
                    }
                )
            except (KeyError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
                base_record.update(
                    {
                        "passed": False,
                        "checks": [],
                        "latency_ms": round(
                            (time.perf_counter() - started) * 1000,
                            2,
                        ),
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "model_call_count": 0,
                        "error_code": _safe_error_code(exc),
                    }
                )
            records.append(base_record)
            total_input_tokens += int(base_record["input_tokens"])
            total_output_tokens += int(base_record["output_tokens"])
            total_model_calls += int(base_record["model_call_count"])

    completed_records = [record for record in records if "error_code" not in record]
    execution_errors = [record for record in records if "error_code" in record]
    category_results: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for record in completed_records:
        category_results[record["category"]][0] += int(record["passed"])
        category_results[record["category"]][1] += 1
    passed_runs = sum(int(record["passed"]) for record in completed_records)
    completed_runs = len(completed_records)
    latencies = [
        float(latency)
        for record in completed_records
        for latency in record["request_latencies_ms"]
    ]
    estimated_cost = (
        total_input_tokens * float(model["input_cost_per_million"])
        + total_output_tokens * float(model["output_cost_per_million"])
    ) / 1_000_000
    report = {
        "role": model["role"],
        "name": model["name"],
        "model_id": model["model_id"],
        "foundation_model_id": model["foundation_model_id"],
        "aws_region": model["aws_region"],
        "invocation_type": model["invocation_type"],
        "geography": model["geography"],
        "deployment_source_regions": model["deployment_source_regions"],
        "catalog": inspect_catalog(model),
        "entitlement_verified": total_model_calls > 0,
        "repeats": repeats,
        "total_runs": len(records),
        "completed_runs": completed_runs,
        "execution_error_count": len(execution_errors),
        "execution_error_codes": sorted(
            {str(record["error_code"]) for record in execution_errors}
        ),
        "passed_runs": passed_runs,
        "pass_rate": round(passed_runs / completed_runs, 4)
        if completed_runs
        else 0.0,
        "category_pass_rates": {
            category: round(passed / total, 4)
            for category, (passed, total) in sorted(category_results.items())
        },
        "latency_ms": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "token_usage": {
            "input": total_input_tokens,
            "output": total_output_tokens,
            "total": total_input_tokens + total_output_tokens,
            "model_calls": total_model_calls,
        },
        "cost_estimate": {
            "currency": "USD",
            "input_per_million_tokens": model["input_cost_per_million"],
            "output_per_million_tokens": model["output_cost_per_million"],
            "estimated_total": round(estimated_cost, 6),
        },
        "availability_source": model["availability_source"],
        "pricing_source": model["pricing_source"],
        "pricing_checked_on": model["pricing_checked_on"],
        "commit_sha": commit_sha,
        "records": records,
    }
    return report, review_items


def assess_model(report: dict[str, Any], selection: dict[str, Any]) -> list[str]:
    failures = []
    if not report["catalog"].get("verified"):
        failures.append("CATALOG_NOT_VERIFIED")
    if not report["entitlement_verified"]:
        failures.append("ACCOUNT_ENTITLEMENT_NOT_VERIFIED")
    if report["execution_error_count"]:
        failures.append("EXECUTION_ERRORS_PRESENT")
    if (
        report["aws_region"] != selection["required_deployment_region"]
        or selection["required_deployment_region"]
        not in report["deployment_source_regions"]
    ):
        failures.append("REQUIRED_DEPLOYMENT_REGION_UNAVAILABLE")
    if report["geography"] != selection["required_geography"]:
        failures.append("REQUIRED_GEOGRAPHY_MISMATCH")
    if float(report["pass_rate"]) < float(selection["minimum_pass_rate"]):
        failures.append("PASS_RATE_BELOW_THRESHOLD")
    for category, minimum in selection["minimum_category_pass_rates"].items():
        if float(report["category_pass_rates"].get(category, 0)) < float(minimum):
            failures.append(f"{category.upper()}_PASS_RATE_BELOW_THRESHOLD")
    p95 = report["latency_ms"]["p95"]
    if p95 is None or float(p95) > float(selection["maximum_p95_ms"]):
        failures.append("P95_LATENCY_ABOVE_THRESHOLD")
    if float(report["cost_estimate"]["estimated_total"]) > float(
        selection["maximum_estimated_cost_usd"]
    ):
        failures.append("ESTIMATED_COST_ABOVE_THRESHOLD")
    return failures


def select_model(reports: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = next(report for report in reports if report["role"] == "baseline")
    candidates = [report for report in reports if report["role"] == "candidate"]
    eligible_candidates = [report for report in candidates if not report["gate_failures"]]
    if baseline["gate_failures"]:
        return {
            "status": "blocked",
            "selected_model_id": None,
            "human_review_required": False,
            "reason_codes": ["BASELINE_FAILED_REQUIRED_GATES"],
        }
    if eligible_candidates:
        return {
            "status": "pending_human_review",
            "selected_model_id": baseline["model_id"],
            "human_review_required": True,
            "eligible_candidate_model_ids": [
                report["model_id"] for report in eligible_candidates
            ],
            "reason_codes": ["SUBJECTIVE_QUALITY_REVIEW_REQUIRED_BEFORE_MODEL_CHANGE"],
        }
    reason_codes = sorted(
        {
            failure
            for candidate in candidates
            for failure in candidate["gate_failures"]
        }
    )
    return {
        "status": "retain_baseline",
        "selected_model_id": baseline["model_id"],
        "human_review_required": False,
        "reason_codes": reason_codes or ["NO_ELIGIBLE_CANDIDATE"],
    }


def _blind_model_labels(comparison_id: str, model_ids: list[str]) -> dict[str, str]:
    ordered = sorted(
        model_ids,
        key=lambda model_id: sha256(
            f"{comparison_id}:{model_id}".encode()
        ).hexdigest(),
    )
    return {model_id: chr(ord("A") + index) for index, model_id in enumerate(ordered)}


def write_human_review(
    path: Path,
    key_path: Path,
    comparison_id: str,
    models: list[dict[str, Any]],
    review_items: list[dict[str, Any]],
) -> None:
    labels = _blind_model_labels(
        comparison_id,
        [model["model_id"] for model in models],
    )
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in review_items:
        grouped[(item["case_id"], item["repeat"])][labels[item["model_id"]]] = item
    label_values = sorted(labels.values())
    if len(label_values) != 2:
        raise ValueError("human review CSV currently requires exactly two models")
    first, second = label_values
    fields = [
        "case_id",
        "category",
        "repeat",
        "messages",
        f"output_{first}",
        f"evidence_{first}",
        f"output_{second}",
        f"evidence_{second}",
        f"explanation_clarity_{first}_1_to_5",
        f"groundedness_{first}_1_to_5_or_na",
        f"uncertainty_calibration_{first}_1_to_5",
        f"safety_helpfulness_{first}_1_to_5",
        f"explanation_clarity_{second}_1_to_5",
        f"groundedness_{second}_1_to_5_or_na",
        f"uncertainty_calibration_{second}_1_to_5",
        f"safety_helpfulness_{second}_1_to_5",
        "preferred_output",
        "reviewer_notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (case_id, repeat), items in sorted(grouped.items()):
            if first not in items or second not in items:
                continue
            left = items[first]
            right = items[second]
            writer.writerow(
                {
                    "case_id": case_id,
                    "category": left["category"],
                    "repeat": repeat,
                    "messages": json.dumps(left["messages"], ensure_ascii=True),
                    f"output_{first}": "\n\n".join(left["answers"]),
                    f"evidence_{first}": json.dumps(
                        {
                            key: left[key]
                            for key in ("agent_results", "source_ids", "disclaimers")
                        },
                        ensure_ascii=True,
                    ),
                    f"output_{second}": "\n\n".join(right["answers"]),
                    f"evidence_{second}": json.dumps(
                        {
                            key: right[key]
                            for key in ("agent_results", "source_ids", "disclaimers")
                        },
                        ensure_ascii=True,
                    ),
                }
            )
    key_path.write_text(
        json.dumps(
            {
                "comparison_id": comparison_id,
                "labels": {label: model_id for model_id, label in labels.items()},
                "rubric": {
                    "scale": "1=unacceptable, 3=adequate, 5=excellent",
                    "groundedness": "Use NA when the case has no retrieved evidence.",
                    "preferred_output": f"Enter {first}, {second}, or tie.",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def write_job_summary(report: dict[str, Any]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## Bedrock model comparison",
        "",
        "| Model | Structural pass | P95 | Estimated cost | Selection gates |",
        "|---|---:|---:|---:|---|",
    ]
    for model in report["models"]:
        gate = "PASS" if not model["gate_failures"] else ", ".join(model["gate_failures"])
        lines.append(
            f"| {model['name']} | {model['pass_rate']:.1%} | "
            f"{model['latency_ms']['p95']} ms | "
            f"USD {model['cost_estimate']['estimated_total']:.6f} | {gate} |"
        )
    decision = report["decision"]
    lines.extend(
        [
            "",
            f"- Decision status: **{decision['status']}**",
            f"- Selected model: `{decision['selected_model_id']}`",
            f"- Evidence complete: **{report['passed']}**",
        ]
    )
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare approved Bedrock models through the multi-agent orchestrator"
    )
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--human-review-output", required=True, type=Path)
    parser.add_argument("--review-key-output", required=True, type=Path)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", "unknown"))
    args = parser.parse_args()

    policy = load_policy(args.policy)
    repeats = args.repeats if args.repeats is not None else int(policy["repeats"])
    if repeats not in range(1, 6):
        parser.error("--repeats must be between 1 and 5")
    cases_path = REPO_ROOT / policy["cases"]
    cases = load_cases(cases_path)

    reports = []
    review_items = []
    for model in policy["models"]:
        model_report, model_review = run_model(
            model,
            cases,
            repeats,
            policy["prompt_set_version"],
            args.commit_sha,
        )
        model_report["gate_failures"] = assess_model(
            model_report,
            policy["selection"],
        )
        reports.append(model_report)
        review_items.extend(model_review)

    decision = select_model(reports)
    baseline = next(report for report in reports if report["role"] == "baseline")
    comparison_failures = []
    if baseline["gate_failures"]:
        comparison_failures.append("BASELINE_FAILED_REQUIRED_GATES")
    for model in reports:
        if not model["catalog"].get("verified"):
            comparison_failures.append(f"{model['model_id']}:CATALOG_NOT_VERIFIED")
        if not model["entitlement_verified"]:
            comparison_failures.append(
                f"{model['model_id']}:ACCOUNT_ENTITLEMENT_NOT_VERIFIED"
            )
        if model["execution_error_count"]:
            comparison_failures.append(
                f"{model['model_id']}:EXECUTION_ERRORS_PRESENT"
            )
    report = {
        "schema_version": 1,
        "comparison_id": policy["comparison_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": args.commit_sha,
        "prompt_set_version": policy["prompt_set_version"],
        "case_count": len(cases),
        "repeats": repeats,
        "selection_policy": policy["selection"],
        "models": reports,
        "decision": decision,
        "comparison_failures": comparison_failures,
        "passed": not comparison_failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_human_review(
        args.human_review_output,
        args.review_key_output,
        policy["comparison_id"],
        policy["models"],
        review_items,
    )
    write_job_summary(report)
    print(
        json.dumps(
            {
                "comparison_id": report["comparison_id"],
                "models": [
                    {
                        "model_id": model["model_id"],
                        "pass_rate": model["pass_rate"],
                        "p95_ms": model["latency_ms"]["p95"],
                        "estimated_cost_usd": model["cost_estimate"]["estimated_total"],
                        "gate_failures": model["gate_failures"],
                    }
                    for model in reports
                ],
                "decision": decision,
                "comparison_failures": comparison_failures,
                "passed": report["passed"],
            },
            indent=2,
        )
    )
    if comparison_failures:
        raise SystemExit("Model comparison evidence was incomplete")


if __name__ == "__main__":
    main()
