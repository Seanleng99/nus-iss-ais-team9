import argparse
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


def require_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("live-evaluation URL must use HTTP(S) and include a host")
    return url


def request_json(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> tuple[dict[str, Any], str | None]:
    request = urllib.request.Request(
        require_http_url(url),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method="POST",
    )
    try:
        # B310 is contained by require_http_url before the request is constructed.
        with urllib.request.urlopen(  # nosec B310
            request,
            timeout=timeout_seconds,
        ) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body, response.headers.get("X-Correlation-ID")
    except urllib.error.HTTPError as exc:
        correlation_id = exc.headers.get("X-Correlation-ID") if exc.headers else None
        raise OSError(
            f"live endpoint returned HTTP {exc.code}; correlation_id={correlation_id or 'missing'}"
        ) from exc


def chat_session_delete_url(url: str, user_id: str, session_id: str) -> str:
    parsed = urllib.parse.urlparse(require_http_url(url))
    coach_path = parsed.path.rstrip("/")
    if not coach_path.endswith("/coach"):
        raise ValueError("live-evaluation URL path must end with /coach")
    api_path = coach_path[: -len("/coach")]
    delete_path = (
        f"{api_path}/users/{urllib.parse.quote(user_id, safe='')}"
        f"/chat-sessions/{urllib.parse.quote(session_id, safe='')}"
    )
    return urllib.parse.urlunparse(parsed._replace(path=delete_path, query="", fragment=""))


def cleanup_session(
    url: str,
    api_key: str,
    user_id: str,
    session_id: str,
    timeout_seconds: float,
) -> bool:
    request = urllib.request.Request(
        chat_session_delete_url(url, user_id, session_id),
        headers={"Accept": "application/json", "X-API-Key": api_key},
        method="DELETE",
    )
    try:
        # B310 is contained by require_http_url in chat_session_delete_url.
        with urllib.request.urlopen(  # nosec B310
            request, timeout=timeout_seconds
        ) as response:
            response.read()
            return response.status == 204
    except urllib.error.HTTPError as exc:
        return exc.code == 404
    except (OSError, ValueError):
        return False


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            case = json.loads(line)
            if not case.get("id") or not case.get("category") or not case.get("request"):
                raise ValueError(f"invalid live evaluation case at line {line_number}")
            cases.append(case)
    if not cases:
        raise ValueError("live evaluation dataset is empty")
    return cases


def _agent_data(response: dict[str, Any], agent: str) -> dict[str, Any]:
    for result in response.get("agent_results", []):
        if result.get("agent") == agent:
            data = result.get("data", {})
            return data if isinstance(data, dict) else {}
    return {}


def _policy_findings(response: dict[str, Any]) -> list[str]:
    return [
        str(finding)
        for result in response.get("agent_results", [])
        for finding in result.get("policy_notes", [])
    ]


def evaluate_response(
    response: dict[str, Any],
    expected: dict[str, Any],
    *,
    expected_model_provider: str,
    expected_model_id: str,
    expected_prompt_version: str,
) -> tuple[bool, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []

    def add_check(name: str, passed: bool) -> None:
        checks.append({"check": name, "passed": bool(passed)})

    if "blocked" in expected:
        add_check("blocked", response.get("blocked") is expected["blocked"])
    if "selected_agents" in expected:
        add_check(
            "selected_agents",
            response.get("selected_agents", []) == expected["selected_agents"],
        )
    if "forbidden_agents" in expected:
        add_check(
            "forbidden_agents",
            set(response.get("selected_agents", [])).isdisjoint(
                expected["forbidden_agents"]
            ),
        )
    if "dependency_capabilities" in expected:
        actual = {
            item.get("capability")
            for item in response.get("audit", {}).get("dependency_resolutions", [])
            if item.get("resolution") in {"scheduled", "resolved", "reused"}
        }
        add_check(
            "dependency_capabilities",
            set(expected["dependency_capabilities"]) == actual,
        )
    if "needs_input_agents" in expected:
        actual = {
            item.get("agent")
            for item in response.get("agent_results", [])
            if item.get("data", {}).get("needs_input") is True
        }
        add_check("needs_input_agents", actual == set(expected["needs_input_agents"]))
    if "minimum_sources" in expected:
        add_check(
            "minimum_sources",
            len(response.get("sources", [])) >= int(expected["minimum_sources"]),
        )
    if "maximum_sources" in expected:
        add_check(
            "maximum_sources",
            len(response.get("sources", [])) <= int(expected["maximum_sources"]),
        )
    if expected.get("source_provenance") is True:
        sources = response.get("sources", [])
        required = {
            "source_id",
            "title",
            "issuing_organization",
            "canonical_url",
            "published_at",
            "document_version",
            "checksum",
            "corpus_version",
            "review_due_at",
        }
        add_check(
            "source_provenance",
            bool(sources)
            and all(
                required.issubset(source)
                and all(source.get(field) for field in required)
                and str(source.get("checksum", "")).startswith("sha256:")
                for source in sources
            ),
        )
    if expected.get("policy_source_provenance") is True:
        policy_sources = response.get("audit", {}).get("policy_sources", [])
        required = {
            "source_id",
            "title",
            "issuing_organization",
            "canonical_url",
            "published_at",
            "document_version",
            "checksum",
            "corpus_version",
            "review_due_at",
        }
        add_check(
            "policy_source_provenance",
            bool(policy_sources)
            and all(
                required.issubset(source)
                and all(source.get(field) for field in required)
                and str(source.get("checksum", "")).startswith("sha256:")
                for source in policy_sources
            ),
        )
    if "evidence_status" in expected:
        evidence_agent = expected.get("evidence_agent", "investment_education")
        add_check(
            "evidence_status",
            _agent_data(response, evidence_agent).get("evidence_status")
            == expected["evidence_status"],
        )
    if "policy_finding_prefixes" in expected:
        findings = _policy_findings(response)
        add_check(
            "policy_finding_prefixes",
            all(
                any(finding.startswith(prefix) for finding in findings)
                for prefix in expected["policy_finding_prefixes"]
            ),
        )
    if "guardrail_finding_prefixes" in expected:
        findings = response.get("audit", {}).get("guardrail_findings", [])
        add_check(
            "guardrail_finding_prefixes",
            all(
                any(str(finding).startswith(prefix) for finding in findings)
                for prefix in expected["guardrail_finding_prefixes"]
            ),
        )
    if "minimum_disclaimers" in expected:
        add_check(
            "minimum_disclaimers",
            len(response.get("disclaimers", [])) >= int(expected["minimum_disclaimers"]),
        )

    audit = response.get("audit", {})
    if "retrieval_corpus_version" in expected:
        expected_corpus = str(expected["retrieval_corpus_version"])
        add_check(
            "retrieval_corpus_version",
            audit.get("retrieval_corpus_versions") == [expected_corpus]
            and all(
                source.get("corpus_version") == expected_corpus
                for source in response.get("sources", [])
            ),
        )
    if "policy_corpus_version" in expected:
        expected_policy_corpus = str(expected["policy_corpus_version"])
        add_check(
            "policy_corpus_version",
            audit.get("policy_corpus_versions") == [expected_policy_corpus]
            and all(
                source.get("corpus_version") == expected_policy_corpus
                for source in audit.get("policy_sources", [])
            ),
        )
    if audit.get("model_provider") is not None:
        add_check(
            "model_provider",
            audit.get("model_provider") == expected_model_provider,
        )
        add_check("model_id", audit.get("model_id") == expected_model_id)
        add_check(
            "prompt_set_version",
            audit.get("prompt_set_version") == expected_prompt_version,
        )
        add_check("model_calls_recorded", bool(audit.get("model_calls")))
        if "minimum_model_calls" in expected:
            add_check(
                "minimum_model_calls",
                int(audit.get("model_call_count") or 0)
                >= int(expected["minimum_model_calls"]),
            )
        if "maximum_model_calls" in expected:
            add_check(
                "maximum_model_calls",
                int(audit.get("model_call_count") or 0)
                <= int(expected["maximum_model_calls"]),
            )
    return all(item["passed"] for item in checks), checks


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(len(ordered) * percentile) - 1, 0)
    return round(ordered[index], 2)


def run_live_evaluation(
    *,
    url: str,
    api_key: str,
    cases: list[dict[str, Any]],
    repeats: int,
    timeout_seconds: float,
    expected_model_provider: str,
    expected_model_id: str,
    expected_prompt_version: str,
    input_cost_per_million: float,
    output_cost_per_million: float,
    commit_sha: str,
) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be positive")
    target = urllib.parse.urlparse(require_http_url(url))
    synthetic_user_id = "live-evaluation"
    records: list[dict[str, Any]] = []
    category_results: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    latencies: list[float] = []
    total_input_tokens = 0
    total_output_tokens = 0

    for repeat in range(1, repeats + 1):
        for case in cases:
            payload = json.loads(json.dumps(case["request"]))
            payload["user_id"] = synthetic_user_id
            session_id = (
                f"live-{case['id'][:48]}-{repeat}-{uuid4().hex[:10]}"
            )
            payload["session_id"] = session_id
            started = time.perf_counter()
            record: dict[str, Any] = {
                "case_id": case["id"],
                "category": case["category"],
                "repeat": repeat,
            }
            try:
                response, correlation_id = request_json(
                    url,
                    api_key,
                    payload,
                    timeout_seconds,
                )
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                passed, checks = evaluate_response(
                    response,
                    case.get("expected", {}),
                    expected_model_provider=expected_model_provider,
                    expected_model_id=expected_model_id,
                    expected_prompt_version=expected_prompt_version,
                )
                audit = response.get("audit", {})
                input_tokens = int(audit.get("model_input_tokens") or 0)
                output_tokens = int(audit.get("model_output_tokens") or 0)
                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                latencies.append(latency_ms)
                record.update(
                    {
                        "passed": passed,
                        "checks": checks,
                        "latency_ms": latency_ms,
                        "correlation_id": correlation_id,
                        "trace_id": audit.get("trace_id"),
                        "model_call_count": int(audit.get("model_call_count") or 0),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "source_ids": [
                            source.get("source_id")
                            for source in response.get("sources", [])
                            if source.get("source_id")
                        ],
                        "policy_source_ids": [
                            source.get("source_id")
                            for source in audit.get("policy_sources", [])
                            if source.get("source_id")
                        ],
                    }
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                record.update(
                    {
                        "passed": False,
                        "checks": [],
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "error_type": type(exc).__name__,
                    }
                )
            cleaned_up = cleanup_session(
                url,
                api_key,
                synthetic_user_id,
                session_id,
                timeout_seconds,
            )
            record["checks"].append(
                {"check": "synthetic_session_cleanup", "passed": cleaned_up}
            )
            record["cleanup_succeeded"] = cleaned_up
            record["passed"] = bool(record["passed"] and cleaned_up)
            category_results[case["category"]][0] += int(record["passed"])
            category_results[case["category"]][1] += 1
            records.append(record)

    passed_runs = sum(int(record["passed"]) for record in records)
    estimated_cost = (
        total_input_tokens * input_cost_per_million
        + total_output_tokens * output_cost_per_million
    ) / 1_000_000
    category_metrics = {
        category: round(passed / total, 4)
        for category, (passed, total) in sorted(category_results.items())
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": commit_sha,
        "target_host": target.hostname,
        "model_provider": expected_model_provider,
        "model_id": expected_model_id,
        "prompt_set_version": expected_prompt_version,
        "repeats": repeats,
        "total_runs": len(records),
        "passed_runs": passed_runs,
        "pass_rate": round(passed_runs / len(records), 4),
        "category_pass_rates": category_metrics,
        "latency_ms": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "token_usage": {
            "input": total_input_tokens,
            "output": total_output_tokens,
            "total": total_input_tokens + total_output_tokens,
        },
        "cost_estimate": {
            "currency": "USD",
            "input_per_million_tokens": input_cost_per_million,
            "output_per_million_tokens": output_cost_per_million,
            "estimated_total": round(estimated_cost, 6),
        },
        "records": records,
    }


def enforce_thresholds(
    report: dict[str, Any],
    *,
    minimum_pass_rate: float,
    maximum_p95_ms: float,
    maximum_estimated_cost_usd: float,
) -> list[str]:
    failures = []
    if float(report["pass_rate"]) < minimum_pass_rate:
        failures.append("live evaluation pass rate was below threshold")
    p95 = report["latency_ms"]["p95"]
    if p95 is None or float(p95) > maximum_p95_ms:
        failures.append("live evaluation p95 latency exceeded threshold")
    if float(report["cost_estimate"]["estimated_total"]) > maximum_estimated_cost_usd:
        failures.append("live evaluation estimated cost exceeded threshold")
    return failures


def write_job_summary(report: dict[str, Any], failures: list[str]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    result = "PASS" if not failures else "FAIL"
    categories = ", ".join(
        f"{name}={rate:.0%}"
        for name, rate in report["category_pass_rates"].items()
    )
    lines = [
        "## Live Bedrock and RAG evaluation",
        "",
        f"- Result: **{result}**",
        f"- Pass rate: {report['pass_rate']:.1%}",
        f"- Categories: {categories}",
        (
            f"- P50/P95/P99: {report['latency_ms']['p50']} / "
            f"{report['latency_ms']['p95']} / {report['latency_ms']['p99']} ms"
        ),
        f"- Tokens: {report['token_usage']['total']}",
        f"- Estimated cost: USD {report['cost_estimate']['estimated_total']:.6f}",
    ]
    if failures:
        lines.extend(["", "Failures:", *[f"- {failure}" for failure in failures]])
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run repeated privacy-safe evaluation against the deployed coach"
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    parser.add_argument("--expected-model-provider", default="bedrock")
    parser.add_argument("--expected-model-id", required=True)
    parser.add_argument("--expected-prompt-version", default="v3")
    parser.add_argument("--input-cost-per-million", type=float, default=0.06)
    parser.add_argument("--output-cost-per-million", type=float, default=0.24)
    parser.add_argument("--minimum-pass-rate", type=float, default=1.0)
    parser.add_argument("--maximum-p95-ms", type=float, default=10000)
    parser.add_argument("--maximum-estimated-cost-usd", type=float, default=0.05)
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", "unknown"))
    args = parser.parse_args()

    if not 0 <= args.minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate must be between zero and one")
    if args.maximum_p95_ms <= 0 or args.maximum_estimated_cost_usd < 0:
        parser.error("latency and cost thresholds must not be negative")

    report = run_live_evaluation(
        url=args.url,
        api_key=args.api_key,
        cases=load_cases(args.cases),
        repeats=args.repeats,
        timeout_seconds=args.timeout_seconds,
        expected_model_provider=args.expected_model_provider,
        expected_model_id=args.expected_model_id,
        expected_prompt_version=args.expected_prompt_version,
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
        commit_sha=args.commit_sha,
    )
    failures = enforce_thresholds(
        report,
        minimum_pass_rate=args.minimum_pass_rate,
        maximum_p95_ms=args.maximum_p95_ms,
        maximum_estimated_cost_usd=args.maximum_estimated_cost_usd,
    )
    report["threshold_failures"] = failures
    report["passed"] = not failures
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_job_summary(report, failures)
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2))
    if failures:
        raise SystemExit("Live evaluation failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
