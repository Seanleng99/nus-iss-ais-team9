import argparse
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def require_http_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("smoke-test URL must use HTTP(S) and include a host")
    return url


def chat_session_delete_url(url: str, user_id: str, session_id: str) -> str:
    parsed = urllib.parse.urlparse(require_http_url(url))
    coach_path = parsed.path.rstrip("/")
    if not coach_path.endswith("/coach"):
        raise ValueError("load-test URL path must end with /coach")
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


def send_request(
    url: str, api_key: str, timeout_seconds: float
) -> tuple[int, float, bool]:
    request_id = str(uuid4())
    user_id = f"load-test-user-{request_id}"
    session_id = request_id
    payload = {
        "user_id": user_id,
        "session_id": session_id,
        "message": "Create a monthly budget",
        "snapshot": {
            "monthly_income": {"currency": "SGD", "amount": 4000},
            "recurring_expenses": [],
        },
    }
    request = urllib.request.Request(
        require_http_url(url),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    started = time.perf_counter()
    try:
        # B310 is contained by require_http_url before the request is constructed.
        with urllib.request.urlopen(  # nosec B310
            request, timeout=timeout_seconds
        ) as response:
            response.read()
            status = response.status
            latency_ms = (time.perf_counter() - started) * 1000
    finally:
        cleaned_up = cleanup_session(
            url, api_key, user_id, session_id, timeout_seconds
        )
    return status, latency_ms, cleaned_up


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(len(ordered) * fraction) - 1, 0)
    return round(ordered[index], 2)


def build_report(
    *,
    url: str,
    request_count: int,
    concurrency: int,
    latencies: list[float],
    failures: list[str],
    cleanup_failures: int,
    elapsed_seconds: float,
    commit_sha: str,
) -> dict[str, object]:
    success_rate = len(latencies) / request_count
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "commit_sha": commit_sha,
        "target_host": urllib.parse.urlparse(require_http_url(url)).hostname,
        "requests": request_count,
        "concurrency": concurrency,
        "successes": len(latencies),
        "success_rate": round(success_rate, 4),
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "elapsed_seconds": round(elapsed_seconds, 2),
        "failure_types": sorted(set(failures)),
        "cleanup_failures": cleanup_failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded backend load smoke test")
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--minimum-success-rate", type=float, default=1.0)
    parser.add_argument("--maximum-p95-ms", type=float, default=8000)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", "unknown"))
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")

    latencies: list[float] = []
    failures: list[str] = []
    cleanup_failures = 0
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(send_request, args.url, args.api_key, args.timeout_seconds)
            for _ in range(args.requests)
        ]
        for future in as_completed(futures):
            try:
                status, latency, cleaned_up = future.result()
                if status == 200:
                    latencies.append(latency)
                else:
                    failures.append(f"HTTP {status}")
                cleanup_failures += int(not cleaned_up)
            except (OSError, ValueError) as error:
                failures.append(type(error).__name__)

    report = build_report(
        url=args.url,
        request_count=args.requests,
        concurrency=args.concurrency,
        latencies=latencies,
        failures=failures,
        cleanup_failures=cleanup_failures,
        elapsed_seconds=time.perf_counter() - started,
        commit_sha=args.commit_sha,
    )
    p95_ms = report["latency_ms"]["p95"]
    threshold_failures = []
    if report["success_rate"] < args.minimum_success_rate:
        threshold_failures.append("success rate was below threshold")
    if p95_ms is None or p95_ms > args.maximum_p95_ms:
        threshold_failures.append("p95 latency exceeded threshold")
    if cleanup_failures:
        threshold_failures.append("one or more synthetic chat sessions were not deleted")
    report["threshold_failures"] = threshold_failures
    report["passed"] = not threshold_failures
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if threshold_failures:
        raise SystemExit("Load smoke failed: " + "; ".join(threshold_failures))


if __name__ == "__main__":
    main()
