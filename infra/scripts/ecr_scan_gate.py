import argparse
import json
import subprocess
import time
from collections import Counter

READY_STATUSES = {"ACTIVE", "COMPLETE"}
FAILED_STATUSES = {"FAILED", "UNSUPPORTED_IMAGE", "SCAN_ELIGIBILITY_EXPIRED"}


def describe_findings(repository: str, image_tag: str) -> dict | None:
    command = [
        "aws",
        "ecr",
        "describe-image-scan-findings",
        "--repository-name",
        repository,
        "--image-id",
        f"imageTag={image_tag}",
        "--output",
        "json",
        "--no-cli-pager",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode == 0:
        return json.loads(completed.stdout)
    retryable_errors = ("ScanNotFoundException", "ImageNotFoundException", "LIMIT_EXCEEDED")
    if any(error in completed.stderr for error in retryable_errors):
        return None
    raise RuntimeError(completed.stderr.strip() or "Unable to query ECR scan findings")


def wait_for_findings(
    repository: str,
    image_tag: str,
    attempts: int,
    interval_seconds: int,
    settle_seconds: int,
) -> dict:
    active_since: float | None = None
    for attempt in range(1, attempts + 1):
        response = describe_findings(repository, image_tag)
        if response is not None:
            status = response.get("imageScanStatus", {}).get("status", "UNKNOWN")
            if status in FAILED_STATUSES:
                raise RuntimeError(f"ECR scan entered terminal status {status}")
            if status == "COMPLETE":
                return response
            if status in READY_STATUSES:
                active_since = active_since or time.monotonic()
                if time.monotonic() - active_since >= settle_seconds:
                    return response
        if attempt < attempts:
            time.sleep(interval_seconds)
    raise TimeoutError(
        "No usable ECR scan result was available. Enable scan-on-push or Inspector "
        "enhanced scanning for this repository."
    )


def severity_counts(response: dict) -> Counter:
    scan_findings = response.get("imageScanFindings", {})
    findings = scan_findings.get("enhancedFindings") or scan_findings.get("findings") or []
    return Counter(str(finding.get("severity", "UNDEFINED")).upper() for finding in findings)


def blocking_findings(response: dict) -> list[dict]:
    scan_findings = response.get("imageScanFindings", {})
    findings = scan_findings.get("enhancedFindings") or scan_findings.get("findings") or []
    summaries = []
    for finding in findings:
        severity = str(finding.get("severity", "UNDEFINED")).upper()
        if severity not in {"CRITICAL", "HIGH"}:
            continue
        vulnerability = finding.get("packageVulnerabilityDetails", {})
        packages = vulnerability.get("vulnerablePackages", [])
        attributes = {
            attribute.get("key"): attribute.get("value")
            for attribute in finding.get("attributes", [])
            if attribute.get("key")
        }
        summaries.append(
            {
                "severity": severity,
                "id": vulnerability.get("vulnerabilityId")
                or finding.get("name")
                or finding.get("title"),
                "fix_available": finding.get("fixAvailable"),
                "source": finding.get("sourceUrl") or finding.get("uri"),
                "packages": [
                    {
                        "name": package.get("name"),
                        "version": package.get("version"),
                        "fixed_in_version": package.get("fixedInVersion"),
                        "package_manager": package.get("packageManager"),
                    }
                    for package in packages
                ],
                "attributes": attributes,
            }
        )
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail a release on ECR image vulnerabilities")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--max-critical", type=int, default=0)
    parser.add_argument("--max-high", type=int, default=0)
    parser.add_argument("--attempts", type=int, default=30)
    parser.add_argument("--interval-seconds", type=int, default=10)
    parser.add_argument("--settle-seconds", type=int, default=60)
    args = parser.parse_args()

    response = wait_for_findings(
        args.repository,
        args.image_tag,
        args.attempts,
        args.interval_seconds,
        args.settle_seconds,
    )
    counts = severity_counts(response)
    summary = {
        "repository": args.repository,
        "image_tag": args.image_tag,
        "scan_status": response.get("imageScanStatus", {}).get("status"),
        "severity_counts": dict(sorted(counts.items())),
        "blocking_findings": blocking_findings(response),
    }
    print(json.dumps(summary, indent=2))
    if counts["CRITICAL"] > args.max_critical or counts["HIGH"] > args.max_high:
        raise SystemExit(
            f"Image scan gate failed: CRITICAL={counts['CRITICAL']}, HIGH={counts['HIGH']}"
        )


if __name__ == "__main__":
    main()
