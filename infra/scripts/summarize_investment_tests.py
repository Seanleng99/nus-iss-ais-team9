"""Render a safe, readable Markdown summary from pytest JUnit XML."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NO_QUESTIONS = "No prompt metadata (see test method)"
NO_RESPONSE_RECORDED = "No agent response recorded"
STATUSES = ("PASSED", "FAILED", "ERROR", "SKIPPED")


def _status(testcase: ET.Element) -> str:
    if testcase.find("error") is not None:
        return "ERROR"
    if testcase.find("failure") is not None:
        return "FAILED"
    if testcase.find("skipped") is not None:
        return "SKIPPED"
    return "PASSED"


def _questions(testcase: ET.Element) -> list[str]:
    values = [
        prop.get("value", "")
        for prop in testcase.findall("./properties/property")
        if prop.get("name") == "test_question"
    ]
    return values or [NO_QUESTIONS]


def _responses(testcase: ET.Element) -> list[dict[str, str | None]]:
    values = []
    for prop in testcase.findall("./properties/property"):
        if prop.get("name") != "test_response":
            continue
        try:
            response = json.loads(prop.get("value", ""))
        except json.JSONDecodeError:
            continue
        if (
            isinstance(response, dict)
            and all(key in response for key in ("question", "answer", "source"))
            and isinstance(response.get("question"), str)
            and (response.get("answer") is None or isinstance(response.get("answer"), str))
            and isinstance(response.get("source"), str)
        ):
            values.append(response)
    return values


def _question_cells(case: ET.Element) -> list[str]:
    responses = _responses(case)
    if not responses:
        return _questions(case)
    questions = [response["question"] for response in responses]
    if len(responses) > 1 or len(_questions(case)) > 1:
        return [f"Turn {index}: {question}" for index, question in enumerate(questions, 1)]
    return questions


def _response_cells(case: ET.Element) -> list[str]:
    responses = _responses(case)
    if not responses:
        return [NO_RESPONSE_RECORDED]
    cells = []
    multi_turn = len(responses) > 1 or len(_questions(case)) > 1
    for index, response in enumerate(responses, 1):
        answer = response["answer"]
        answer_text = "No agent response returned" if answer is None else answer or "(empty response)"
        prefix = f"Turn {index}: " if multi_turn else ""
        cells.append(f"{prefix}{response['source']}: {answer_text}")
    return cells


def _markdown_cell(value: str) -> str:
    # Escape source text before adding HTML line breaks so prompt markup stays inert.
    escaped = html.escape(value, quote=True)
    for char, entity in (
        ("|", "&#124;"),
        ("`", "&#96;"),
        ("[", "&#91;"),
        ("]", "&#93;"),
        ("*", "&#42;"),
        ("_", "&#95;"),
        ("!", "&#33;"),
        ("\\", "&#92;"),
    ):
        escaped = escaped.replace(char, entity)
    return "<br>".join(escaped.splitlines())


def _console_line(value: str) -> str:
    return value.replace("##[", "##\\[")


def _testcases(root: ET.Element) -> list[ET.Element]:
    return list(root.iter("testcase"))


def _summary(title: str, cases: list[ET.Element]) -> str:
    counts = {status: 0 for status in STATUSES}
    for case in cases:
        counts[_status(case)] += 1
    lines = [f"## {title}", ""]
    lines.append(_totals_line(len(cases), counts))
    lines.extend(("", "| Test method | Question / test input | Agent response (captured) | Status | Duration |", "|---|---|---|---:|---:|"))
    for case in cases:
        status = _status(case)
        classname = case.get("classname", "")
        name = case.get("name", "unknown test")
        method = f"{classname}.{name}" if classname else name
        questions = "<br><br>".join(_markdown_cell(question) for question in _question_cells(case))
        responses = "<br><br>".join(_markdown_cell(response) for response in _response_cells(case))
        try:
            duration = f"{float(case.get('time', '0')):.2f}s"
        except ValueError:
            duration = "—"
        lines.append(
            f"| {_markdown_cell(method)} | {questions} | {responses} | {status} | {duration} |"
        )
    return "\n".join(lines) + "\n"


def _totals_line(total: int, counts: dict[str, int]) -> str:
    return (
        f"Ran {total} tests: {counts['PASSED']} passed, {counts['FAILED']} failed, "
        f"{counts['ERROR']} errors, {counts['SKIPPED']} skipped."
    )


def _no_results(title: str) -> str:
    return f"## {title}\n\nNo test results are available.\n"


def _publish(text: str, output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(text + "\n")


def summarize(xml_path: Path, title: str, output: Path | None) -> int:
    try:
        root = ET.parse(xml_path).getroot()
    except (OSError, ET.ParseError):
        _publish(_no_results(title), output)
        print("No test results: JUnit XML is missing or malformed.", file=sys.stderr)
        return 2

    cases = _testcases(root)
    if not cases:
        _publish(_no_results(title), output)
        print("No test results: JUnit XML contains no test cases.", file=sys.stderr)
        return 2

    report = _summary(title, cases)
    _publish(report, output)
    counts = {status: sum(_status(case) == status for case in cases) for status in STATUSES}
    print(title)
    for case in cases:
        status = _status(case)
        method = ".".join(part for part in (case.get("classname", ""), case.get("name", "unknown test")) if part)
        for line in method.splitlines() or [""]:
            print(f"Test method: {_console_line(line)} [{status}]")
        for question in _question_cells(case):
            for line in question.splitlines() or [""]:
                print(f"Question / test input: {_console_line(line)}")
        for response in _response_cells(case):
            for line in response.splitlines() or [""]:
                print(f"Agent response: {_console_line(line)}")
    print(_totals_line(len(cases), counts))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit_xml", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--title", default="Investment test results")
    args = parser.parse_args()
    return summarize(args.junit_xml, args.title, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
