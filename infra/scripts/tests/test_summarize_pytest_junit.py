import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "summarize_pytest_junit.py"
SPEC = importlib.util.spec_from_file_location("summarize_pytest_junit", MODULE_PATH)
assert SPEC and SPEC.loader
summarize = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = summarize  # dataclasses resolve annotations through sys.modules
SPEC.loader.exec_module(summarize)

REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
  <testcase classname="t" name="test_ok[stock_pick]">
    <properties>
      <property name="question" value="Which stock should I buy?" />
      <property name="response" value="I can't choose investments." />
    </properties>
  </testcase>
  <testcase classname="t" name="test_bad"><failure message="assert False">trace</failure></testcase>
  <testcase classname="t" name="test_broken"><error message="collection failure">trace</error></testcase>
  <testcase classname="t" name="test_skip"><skipped message="not on windows" /></testcase>
</testsuite></testsuites>
"""


@pytest.fixture(autouse=True)
def isolate_ci_summary(monkeypatch):
    """Tests opting into summaries use their own temporary destination."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "report.xml"
    path.write_text(text, encoding="utf-8")
    return path


def test_properties_become_question_and_response(tmp_path):
    cases = summarize.parse_report(_write(tmp_path, REPORT))
    first = cases[0]
    assert first.test_id == "test_ok[stock_pick]"
    assert first.outcome == "passed"
    assert first.question == "Which stock should I buy?"
    assert first.response == "I can't choose investments."


def test_outcomes_are_counted_per_status(tmp_path):
    cases = summarize.parse_report(_write(tmp_path, REPORT))
    assert [case.outcome for case in cases] == ["passed", "failed", "error", "skipped"]
    assert cases[1].reason == "assert False"
    markdown = summarize.render("Title", cases)
    assert "**4 tests:** 1 passed, 1 failed, 1 error, 1 skipped" in markdown


def test_missing_properties_render_as_dash(tmp_path):
    cases = summarize.parse_report(_write(tmp_path, REPORT))
    row = next(line for line in summarize.render("T", cases).splitlines() if "test_bad" in line)
    assert row.startswith("| test_bad | — | ❌ failed | — | assert False |")


def test_cells_escape_pipes_and_collapse_newlines():
    case = summarize.CaseResult("test_x", "passed", "a | b\nc", "ok", "")
    row = summarize.render("T", [case]).splitlines()[-1]
    assert "a \\| b c" in row
    assert row.count(" | ") == 4  # five columns, no extra separators


def test_long_cells_are_truncated():
    case = summarize.CaseResult("test_x", "passed", "q", "x" * 1000, "")
    row = summarize.render("T", [case]).splitlines()[-1]
    assert "x" * summarize.MAX_CELL not in row
    assert "…" in row


def test_non_ascii_text_is_preserved(tmp_path):
    # Chinese sample lives in a fixture: ci.yml's scan_chinese.py rejects Han text in code.
    question = json.loads(
        (Path(__file__).parent / "fixtures" / "non_ascii_question.json").read_text(encoding="utf-8")
    )["question"]
    report = REPORT.replace("Which stock should I buy?", question)
    output = tmp_path / "summary.md"
    assert summarize.main([str(_write(tmp_path, report)), "--output", str(output), "--title", "T"]) == 0
    assert question in output.read_text(encoding="utf-8")


def test_summary_is_appended_to_github_step_summary(tmp_path, monkeypatch):
    step_summary = tmp_path / "step.md"
    step_summary.write_text("earlier job output\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    output = tmp_path / "out" / "summary.md"
    assert summarize.main([str(_write(tmp_path, REPORT)), "--output", str(output), "--title", "Offline"]) == 0
    text = step_summary.read_text(encoding="utf-8")
    assert text.startswith("earlier job output\n")
    assert "## Offline" in text
    assert output.read_text(encoding="utf-8").startswith("## Offline")


def test_no_step_summary_env_writes_only_the_output(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    output = tmp_path / "summary.md"
    assert summarize.main([str(_write(tmp_path, REPORT)), "--output", str(output), "--title", "T"]) == 0
    assert output.exists()


def test_missing_report_writes_notice_and_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    output = tmp_path / "summary.md"
    status = summarize.main([str(tmp_path / "absent.xml"), "--output", str(output), "--title", "T"])
    assert status == 1
    assert "No readable test report" in output.read_text(encoding="utf-8")


def test_corrupt_report_writes_notice_and_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    output = tmp_path / "summary.md"
    status = summarize.main([str(_write(tmp_path, "<testsuites><testcase")), "--output", str(output), "--title", "T"])
    assert status == 1
    assert "No readable test report" in output.read_text(encoding="utf-8")
