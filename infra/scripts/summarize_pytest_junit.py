"""Summarise a pytest JUnit XML report as Markdown for GitHub Actions job summaries."""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

MAX_CELL = 300
OUTCOME_LABELS = {
    "passed": "✅ passed",
    "failed": "❌ failed",
    "error": "❌ error",
    "skipped": "⏭️ skipped",
}
_FAILURE_TAGS = {"failure": "failed", "error": "error", "skipped": "skipped"}
EVALUATION_SPEC = Path(__file__).resolve().parents[2] / "infra/llmsecops/agent-evaluation-specs.json"


@dataclass(frozen=True)
class CaseResult:
    test_id: str
    outcome: str
    question: str
    response: str
    reason: str
    expected: str = ""


def parse_report(path: Path) -> list[CaseResult]:
    cases = []
    # The report is pytest's own output from the same CI job, not external input.
    tree = ET.parse(path)  # nosec B314 - trusted, locally generated JUnit XML
    for case in tree.getroot().iter("testcase"):
        properties = {item.get("name"): item.get("value", "") for item in case.iter("property")}
        outcome, reason = "passed", ""
        for tag, label in _FAILURE_TAGS.items():
            node = case.find(tag)
            if node is not None:
                outcome = label
                reason = node.get("message") or (node.text or "").strip()
                break
        cases.append(CaseResult(
            test_id=case.get("name", ""),
            outcome=outcome,
            question=properties.get("question", ""),
            response=properties.get("response", ""),
            reason=reason,
            expected=properties.get("expected", ""),
        ))
    return cases


def _cell(text: str) -> str:
    text = " ".join(text.split()).replace("|", "\\|")
    if not text:
        return "—"
    return text if len(text) <= MAX_CELL else text[: MAX_CELL - 1] + "…"


def render(title: str, cases: list[CaseResult]) -> str:
    totals = ", ".join(
        f"{sum(case.outcome == outcome for case in cases)} {outcome}" for outcome in OUTCOME_LABELS
    )
    include_expected = any(case.expected for case in cases)
    lines = [
        f"## {title}",
        "",
        f"**{len(cases)} tests:** {totals}",
        "",
        ("| Test | Question | Expected output | Result | Response | Failure reason |"
         if include_expected else "| Test | Question | Result | Response | Failure reason |"),
        ("| --- | --- | --- | --- | --- | --- |"
         if include_expected else "| --- | --- | --- | --- | --- |"),
    ]
    lines.extend(
        f"| {_cell(case.test_id)} | {_cell(case.question)} | "
        + (f"{_cell(case.expected)} | " if include_expected else "")
        + f"{OUTCOME_LABELS[case.outcome]} "
        f"| {_cell(case.response)} | {_cell(case.reason)} |"
        for case in cases
    )
    return "\n".join(lines) + "\n"


def evaluation_summary(suite: str, cases: list[CaseResult]) -> tuple[str, dict | None]:
    """Attach the versioned evaluation contract; missing evidence never passes."""
    catalog = json.loads(EVALUATION_SPEC.read_text(encoding="utf-8"))
    definition = catalog["suites"].get(suite)
    if definition is None:
        if suite.startswith("investment-"):
            raise ValueError(f"Missing evaluation definition for {suite}")
        return "", None
    root = EVALUATION_SPEC.parents[2]
    datasets = [
        {**item, "sha256": sha256((root / item["path"]).read_bytes()).hexdigest()}
        for item in definition["datasets"]
    ]
    passed = sum(case.outcome == "passed" for case in cases)
    accepted = bool(cases) and passed == len(cases)
    report = {
        "suite": suite, "spec_version": catalog["version"],
        "commit_sha": os.getenv("GITHUB_SHA"),
        **definition, "datasets": datasets,
        "results": {"total": len(cases), "passed": passed,
                    "assertion_pass_rate": passed / len(cases) if cases else None,
                    "failed_or_unexecuted_ids": [
                        case.test_id for case in cases if case.outcome != "passed"
                    ]},
        "accepted": accepted,
    }
    lines = [
        "### Evaluation definition and acceptance", "",
        f"Measurement: **{definition['measurement']}**. Spec version: {catalog['version']}.", "",
        "| Dataset / test scenarios | Expected output | SHA-256 |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| `{item['path']}` | {_cell(item['expected_outputs'])} | `{item['sha256']}` |"
        for item in datasets
    )
    lines += ["", "**Metric definitions:**", ""]
    lines.extend(f"- {item}" for item in definition["metrics"])
    lines += ["", "**Acceptance criteria:**", ""]
    lines.extend(f"- {item}" for item in definition["acceptance_criteria"])
    rate = f"{passed / len(cases):.2%}" if cases else "not measured"
    lines += [
        "", (f"Measured assertion pass rate: **{rate}** ({passed}/{len(cases)}). "
        f"Acceptance: **{'PASS' if accepted else 'FAIL / incomplete'}**."), "",
        f"Limitations: {definition['limitations']}", "",
    ]
    return "\n".join(lines), report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="pytest JUnit XML report")
    parser.add_argument("--output", type=Path, required=True, help="Markdown file to write")
    parser.add_argument("--title", required=True, help="heading for the summary")
    parser.add_argument("--suite", help="owned suite ID from the evaluation specification")
    parser.add_argument("--evaluation-output", type=Path, help="evaluation contract and results JSON")
    args = parser.parse_args(argv)

    try:
        cases = parse_report(args.report)
        markdown, status = render(args.title, cases), 0
        if args.suite:
            contract, evaluation = evaluation_summary(args.suite, cases)
            markdown = contract + "\n" + markdown
            if evaluation is not None:
                status = 0 if evaluation["accepted"] else 1
                if args.evaluation_output:
                    args.evaluation_output.parent.mkdir(parents=True, exist_ok=True)
                    args.evaluation_output.write_text(json.dumps(evaluation, indent=2) + "\n")
    except (OSError, ET.ParseError, ValueError, KeyError) as exc:
        markdown = (
            f"## {args.title}\n\n❌ No readable test report at `{args.report}` "
            f"({exc.__class__.__name__}).\n"
        )
        status = 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
