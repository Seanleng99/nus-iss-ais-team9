"""Run an owned agent suite or the remaining AI tests from one selection manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPOSITORY_ROOT / "infra/llmsecops/agent-test-suites.json"


def pytest_arguments(suite: str, manifest: dict) -> list[str]:
    if suite == "remaining":
        owned_paths = set(manifest["ci_only_test_paths"])
        for selection in manifest["suites"].values():
            owned_paths.update(selection["test_paths"])
        return ["tests", *(f"--ignore={path}" for path in sorted(owned_paths))]
    selection = manifest["suites"][suite]
    prefix = selection.get("name_prefix")
    prefix_path = selection.get("name_prefix_test_path")
    args = [path for path in selection["test_paths"] if path != prefix_path]
    if prefix and prefix_path:
        args.append(f"{prefix_path}::{prefix}")
    elif prefix:
        args.extend(["-k", prefix])
    return args


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=["remaining", *manifest["suites"]])
    parser.add_argument("--junitxml", required=True, type=Path)
    args = parser.parse_args()
    report_path = args.junitxml.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-vv", "-o", "junit_family=xunit1", "-o", "xfail_strict=true",
         *pytest_arguments(args.suite, manifest), f"--junitxml={report_path}"],
        cwd=REPOSITORY_ROOT / "apps/ai-service",
    )


if __name__ == "__main__":
    raise SystemExit(main())
