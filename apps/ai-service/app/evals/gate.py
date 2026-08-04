import argparse
import json
import os
from pathlib import Path

from app.evals.runner import run_dataset


def evaluate_policy(policy_path: Path) -> tuple[dict, bool]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    report = {"policy_version": policy["version"], "datasets": [], "passed": True}

    for suite in policy["suites"]:
        metrics = run_dataset(Path(suite["dataset"]))
        checks = []
        for metric_name, minimum in suite["minimums"].items():
            actual = metrics.get(metric_name)
            passed = actual is not None and float(actual) >= float(minimum)
            checks.append(
                {
                    "check": "minimum",
                    "metric": metric_name,
                    "actual": actual,
                    "minimum": minimum,
                    "passed": passed,
                }
            )
            report["passed"] = report["passed"] and passed
        for metric_name, baseline in suite.get("baselines", {}).items():
            actual = metrics.get(metric_name)
            max_regression = suite.get("max_regression", {}).get(metric_name, 0)
            regression = None if actual is None else max(float(baseline) - float(actual), 0)
            passed = regression is not None and regression <= float(max_regression)
            checks.append(
                {
                    "check": "regression",
                    "metric": metric_name,
                    "actual": actual,
                    "baseline": baseline,
                    "regression": regression,
                    "max_regression": max_regression,
                    "passed": passed,
                }
            )
            report["passed"] = report["passed"] and passed
        report["datasets"].append(
            {
                "name": suite["name"],
                "dataset": suite["dataset"],
                "metrics": metrics,
                "checks": checks,
            }
        )
    return report, bool(report["passed"])


def write_job_summary(report: dict) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## LLMSecOps evaluation gate",
        "",
        "| Suite | Check | Metric | Actual | Requirement | Result |",
        "|---|---|---|---:|---:|---|",
    ]
    for suite in report["datasets"]:
        for check in suite["checks"]:
            result = "PASS" if check["passed"] else "FAIL"
            requirement = (
                f">= {check['minimum']}"
                if check["check"] == "minimum"
                else f"drop <= {check['max_regression']}"
            )
            lines.append(
                f"| {suite['name']} | {check['check']} | {check['metric']} | "
                f"{check['actual']} | {requirement} | {result} |"
            )
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce the repository LLMSecOps policy")
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    report, passed = evaluate_policy(args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    write_job_summary(report)
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit("LLMSecOps evaluation policy failed")


if __name__ == "__main__":
    main()
