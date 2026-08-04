import argparse
import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4


def send_request(url: str, api_key: str, timeout_seconds: float) -> tuple[int, float]:
    payload = {
        "user_id": "load-test-user",
        "session_id": str(uuid4()),
        "message": "Create a monthly budget",
        "snapshot": {
            "monthly_income": {"currency": "SGD", "amount": 4000},
            "recurring_expenses": [],
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response.read()
        return response.status, (time.perf_counter() - started) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded backend load smoke test")
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--minimum-success-rate", type=float, default=1.0)
    parser.add_argument("--maximum-p95-ms", type=float, default=5000)
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")

    latencies: list[float] = []
    failures: list[str] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(send_request, args.url, args.api_key, args.timeout_seconds)
            for _ in range(args.requests)
        ]
        for future in as_completed(futures):
            try:
                status, latency = future.result()
                if status == 200:
                    latencies.append(latency)
                else:
                    failures.append(f"HTTP {status}")
            except (OSError, ValueError) as error:
                failures.append(type(error).__name__)

    success_rate = len(latencies) / args.requests
    ordered = sorted(latencies)
    p95_ms = ordered[max(math.ceil(len(ordered) * 0.95) - 1, 0)] if ordered else None
    report = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "successes": len(latencies),
        "success_rate": round(success_rate, 4),
        "p95_ms": round(p95_ms, 2) if p95_ms is not None else None,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "failure_types": sorted(set(failures)),
    }
    print(json.dumps(report, indent=2))
    if success_rate < args.minimum_success_rate:
        raise SystemExit("Load smoke failed its success-rate threshold")
    if p95_ms is None or p95_ms > args.maximum_p95_ms:
        raise SystemExit("Load smoke failed its p95 latency threshold")


if __name__ == "__main__":
    main()
