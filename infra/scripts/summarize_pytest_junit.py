"""Summarise a pytest JUnit XML report as Markdown for GitHub Actions job summaries."""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

MAX_CELL = 300
OUTCOME_LABELS = {
    "passed": "✅ passed",
    "failed": "❌ failed",
    "error": "❌ error",
    "skipped": "⏭️ skipped",
}
_FAILURE_TAGS = {"failure": "failed", "error": "error", "skipped": "skipped"}


@dataclass(frozen=True)
class CaseResult:
    test_id: str
    outcome: str
    question: str
    response: str
    reason: str


def parse_report(path: Path) -> list[CaseResult]:
    cases = []
    for case in ET.parse(path).getroot().iter("testcase"):
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
    lines = [
        f"## {title}",
        "",
        f"**{len(cases)} tests:** {totals}",
        "",
        "| Test | Question | Result | Response | Failure reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {_cell(case.test_id)} | {_cell(case.question)} | {OUTCOME_LABELS[case.outcome]} "
        f"| {_cell(case.response)} | {_cell(case.reason)} |"
        for case in cases
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="pytest JUnit XML report")
    parser.add_argument("--output", type=Path, required=True, help="Markdown file to write")
    parser.add_argument("--title", required=True, help="heading for the summary")
    args = parser.parse_args(argv)

    try:
        markdown, status = render(args.title, parse_report(args.report)), 0
    except (OSError, ET.ParseError) as exc:
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
