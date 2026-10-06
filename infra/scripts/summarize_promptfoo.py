"""Render a safe Markdown summary from Promptfoo JSON evaluation results."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

STATUSES = ("PASSED", "FAILED", "ERROR")
NO_QUESTION = "No question recorded"
NO_RESPONSE = "No response recorded"
NO_REASON = "No grading reason recorded"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _markdown_cell(value: Any) -> str:
    escaped = html.escape(_text(value), quote=True)
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


def _console_line(value: Any) -> str:
    return _text(value).replace("##[", "##\\[")


def _nonempty_error(value: Any) -> str:
    if value is None or value is False or value == "":
        return ""
    return _text(value)


def _test_context(variables: dict[str, Any]) -> str:
    parts = []
    for key, label in (("candidate_answer", "Candidate answer"), ("history", "Conversation history")):
        if key in variables:
            parts.append(f"{label}: {_text(variables[key])}")
    retrieval_case = variables.get("retrieval_case")
    if retrieval_case is not None:
        parts.append(
            f"Retrieval scenario: {_text(retrieval_case)} "
            "(synthetic document fixture: security/promptfoo/provider.py)"
        )
    return "\n".join(parts)


def _row(result: dict[str, Any]) -> dict[str, str]:
    test_case = result.get("testCase")
    response = result.get("response")
    if not isinstance(response, dict):
        response = {}
    response_metadata = response.get("metadata")
    if not isinstance(response_metadata, dict):
        response_metadata = {}
    grading = result.get("gradingResult")
    if not isinstance(grading, dict):
        grading = {}
    variables = test_case.get("vars")
    if not isinstance(variables, dict):
        variables = {}
    metadata = test_case.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    api_error = _nonempty_error(response.get("error")) or _nonempty_error(response_metadata.get("error"))
    if response_metadata.get("runtime_failures"):
        api_error = api_error or _text(response_metadata["runtime_failures"])
    result_error = _nonempty_error(result.get("error"))
    if not isinstance(result.get("response"), dict):
        api_error = api_error or result_error
    if api_error:
        status = "ERROR"
    else:
        passed = grading.get("pass")
        success = result.get("success")
        status = "PASSED" if passed is True and success is not False else "FAILED"

    provider = result.get("provider")
    provider_name = ""
    if isinstance(provider, dict):
        provider_name = _text(provider.get("label")) or _text(provider.get("id"))
    elif isinstance(provider, str):
        provider_name = provider
    target = _text(response_metadata.get("target")) or _text(metadata.get("target"))
    provider_name = (
        provider_name
        or _text(response_metadata.get("provider"))
        or target
        or "Unknown provider"
    )
    owasp = metadata.get("owasp", "")
    if isinstance(owasp, list):
        owasp = ", ".join(_text(item) for item in owasp)
    return {
        "method": _text(test_case.get("description")) or "Unknown test method",
        "provider": provider_name,
        "target": target,
        "mode": _text(response_metadata.get("mode")) or _text(metadata.get("mode")),
        "owasp": _text(owasp),
        "question": _text(variables.get("question")) or NO_QUESTION,
        "test_context": _test_context(variables),
        "response": _text(response.get("output")) or NO_RESPONSE,
        "status": status,
        "reason": _text(grading.get("reason")) or result_error or NO_REASON,
        "api_error": api_error,
    }


def _totals_line(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    return (
        f"Ran {total} Promptfoo tests: {counts['PASSED']} passed, "
        f"{counts['FAILED']} failed, {counts['ERROR']} errors."
    )


def _counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for row in rows:
        counts[row["status"]] += 1
    return counts


def _summary(title: str, rows: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
    counts = _counts(rows)
    lines = [f"## {_markdown_cell(title)}", "", _totals_line(counts), ""]
    providers: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        providers.setdefault(row["provider"], []).append(row)
    for provider, provider_rows in providers.items():
        lines.extend((f"### {_markdown_cell(provider)}", "", _totals_line(_counts(provider_rows)), ""))
        lines.extend(
            (
                "| Test method | OWASP mapping | Target | Mode | Question | Test context | Actual response | Result | API error |",
                "|---|---|---|---|---|---|---|---|---|",
            )
        )
        for row in provider_rows:
            result_text = row["status"] + " — " + row["reason"]
            lines.append(
                "| "
                + " | ".join(
                    _markdown_cell(row[key])
                    for key in ("method", "owasp", "target", "mode", "question", "test_context", "response")
                )
                + " | "
                + _markdown_cell(result_text)
                + " | "
                + _markdown_cell(row["api_error"])
                + " |"
            )
        lines.append("")
    return "\n".join(lines) + "\n", counts


def _no_results(title: str) -> str:
    return f"## {_markdown_cell(title)}\n\nNo Promptfoo results are available.\n"


def _publish(text: str, output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(text + "\n")


def summarize(json_path: Path, title: str, output: Path | None) -> int:
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _publish(_no_results(title), output)
        print("Promptfoo summary: result JSON is missing or malformed.", file=sys.stderr)
        return 2

    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(results, dict):
        results = results.get("results")
    if not isinstance(results, list) or not results or not all(
        isinstance(item, dict)
        and isinstance(item.get("testCase"), dict)
        and isinstance(item["testCase"].get("description"), str)
        and (isinstance(item.get("response"), dict) or bool(_nonempty_error(item.get("error"))))
        and (
            isinstance(item.get("gradingResult"), dict)
            and isinstance(item["gradingResult"].get("pass"), bool)
            or bool(_nonempty_error(item.get("error")))
        )
        for item in results
    ):
        _publish(_no_results(title), output)
        print("Promptfoo summary: result JSON contains no valid results.", file=sys.stderr)
        return 2

    rows = [_row(item) for item in results]
    report, counts = _summary(title, rows)
    _publish(report, output)
    for line in _console_line(title).splitlines() or [""]:
        print(f"Promptfoo summary: {line}")
    for index, row in enumerate(rows, 1):
        for key, label in (
            ("method", "Test method"),
            ("provider", "Provider"),
            ("target", "Target"),
            ("mode", "Mode"),
            ("owasp", "OWASP mapping"),
            ("question", "Question"),
            ("test_context", "Test context"),
            ("response", "Actual response"),
            ("status", "Result"),
            ("reason", "Grading reason"),
            ("api_error", "API error"),
        ):
            for line in _console_line(row[key]).splitlines() or [""]:
                print(f"Promptfoo result {index} {label}: {line}")
    print(f"Promptfoo summary: {_totals_line(counts)}")
    return 1 if counts["FAILED"] or counts["ERROR"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_json", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--title", default="Promptfoo security scan")
    args = parser.parse_args()
    return summarize(args.results_json, args.title, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
