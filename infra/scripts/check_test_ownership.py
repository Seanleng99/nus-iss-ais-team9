"""Require one explicit owner for every actually collected AI/shared pytest case."""

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

try:
    from .run_agent_tests import MANIFEST_PATH, REPOSITORY_ROOT, pytest_arguments
except ImportError:
    from run_agent_tests import MANIFEST_PATH, REPOSITORY_ROOT, pytest_arguments


def collect_nodes(root: Path) -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--color=no", "-p", "no:cacheprovider"],
        cwd=root, env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True,
        text=True, encoding="utf-8", timeout=120, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Pytest collection failed for {root.name}:\n{result.stdout}\n{result.stderr}")
    return [line.strip() for line in result.stdout.splitlines()
            if line.startswith("tests/") and "::" in line]


def matches(node: str, selector: str) -> bool:
    return node == selector or node.startswith((selector + "::", selector + "["))


def validate_ownership(nodes: list[str], selections: dict[str, list[str]], files: set[str]) -> dict:
    errors = []
    counts = Counter()
    declared = set()
    for owner, selectors in selections.items():
        if not selectors:
            errors.append(f"Empty selection: {owner}")
        for selector in selectors:
            path = selector.split("::", 1)[0]
            if (not path.startswith("tests/") or not path.endswith(".py")
                    or ".." in Path(path).parts or "\\" in path):
                errors.append(f"Invalid selector: {owner}: {selector}")
            declared.add(path)
            if not any(matches(node, selector) for node in nodes):
                errors.append(f"Missing or empty selector: {owner}: {selector}")
    errors += [f"Unclassified module: {path}" for path in sorted(files - declared)]
    errors += [f"Missing module: {path}" for path in sorted(declared - files)]
    errors += [f"Duplicate collected node: {node}" for node, count in Counter(nodes).items() if count != 1]
    for node in nodes:
        owners = [owner for owner, selectors in selections.items() for selector in selectors
                  if matches(node, selector)]
        if len(owners) != 1:
            errors.append(f"Expected one owner: {node}: {owners}")
        else:
            counts[owners[0]] += 1
    for owner in selections:
        if not counts[owner]:
            errors.append(f"Empty suite: {owner}")
    if not nodes:
        errors.append("No pytest cases collected")
    return {"passed": not errors, "collected_cases": len(nodes), "owner_counts": dict(counts),
            "errors": errors}


def check_repository(manifest: dict) -> dict:
    results = {}
    for package, owners in (("ai-service", list(manifest["suites"])), ("shared", ["shared"])):
        root = REPOSITORY_ROOT / "apps" / package
        nodes = collect_nodes(root)
        files = {path.relative_to(root).as_posix() for pattern in ("test_*.py", "*_test.py")
                 for path in (root / "tests").rglob(pattern)}
        results[package] = validate_ownership(
            nodes, {owner: pytest_arguments(owner, manifest) for owner in owners}, files,
        )
    return {"schema_version": 1, "commit_sha": os.getenv("GITHUB_SHA"),
            "passed": all(result["passed"] for result in results.values()), "packages": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = check_repository(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        report = {"passed": False, "errors": [str(exc)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
