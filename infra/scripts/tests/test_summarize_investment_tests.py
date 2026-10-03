from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "summarize_investment_tests.py"


class InvestmentSummaryTests(unittest.TestCase):
    def run_report(self, xml: str | None, *, missing: bool = False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        junit = root / "results.xml"
        output = root / "summary.md"
        if xml is not None and not missing:
            junit.write_text(xml, encoding="utf-8")
        env = os.environ.copy()
        env["GITHUB_STEP_SUMMARY"] = str(root / "step-summary.md")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(junit), "--output", str(output), "--title", "Offline results"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        return result, output, root / "step-summary.md"

    def test_counts_mixed_outcomes_from_actual_testcases(self):
        xml = """<testsuites><testsuite>
          <testcase classname="safety" name="passed" time="0.1" />
          <testcase classname="safety" name="failed" time="0.2"><failure message="secret assertion" /></testcase>
          <testcase classname="safety" name="errored" time="0.3"><error message="secret provider" /></testcase>
          <testcase classname="safety" name="skipped" time="0.4"><skipped /></testcase>
        </testsuite></testsuites>"""
        result, output, step_summary = self.run_report(xml)
        self.assertEqual(result.returncode, 0)
        report = output.read_text(encoding="utf-8")
        self.assertIn("| PASSED | 0.10s |", report)
        self.assertIn("| FAILED | 0.20s |", report)
        self.assertIn("| ERROR | 0.30s |", report)
        self.assertIn("| SKIPPED | 0.40s |", report)
        self.assertIn("Ran 4 tests: 1 passed, 1 failed, 1 errors, 1 skipped.", report)
        self.assertIn("Ran 4 tests: 1 passed, 1 failed, 1 errors, 1 skipped.", result.stdout)
        self.assertNotIn("secret", report + result.stdout + result.stderr)
        self.assertIn("Offline results", step_summary.read_text(encoding="utf-8"))

    def test_prompt_text_is_fully_visible_and_markdown_safe(self):
        fixture_path = (
            Path(__file__).resolve().parents[3]
            / "apps/ai-service/tests/fixtures/investment_manual_injection.json"
        )
        unicode_prompt = json.loads(fixture_path.read_text(encoding="utf-8"))[
            "chinese_personal_recommendation"
        ]
        question = f"<system>{unicode_prompt}|` [x](url) *bold* _word_\nsecond line & more</system>"
        escaped_question = (
            question.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("\n", "&#10;")
        )
        xml = f"""<testsuites><testsuite><testcase classname="safety" name="case">
          <properties><property name="test_question" value="{escaped_question}" /></properties>
        </testcase></testsuite></testsuites>"""
        result, output, _ = self.run_report(xml)
        self.assertEqual(result.returncode, 0)
        report = output.read_text(encoding="utf-8")
        self.assertIn(f"&lt;system&gt;{unicode_prompt}&#124;&#96; &#91;x&#93;(url) &#42;bold&#42; &#95;word&#95;<br>second line &amp; more&lt;/system&gt;", report)
        self.assertIn(f"Question / test input: <system>{unicode_prompt}|` [x](url) *bold* _word_", result.stdout)
        self.assertIn("Question / test input: second line & more</system>", result.stdout)
        self.assertNotIn("\nsecond line", result.stdout)

    def test_missing_malformed_and_empty_reports_fail_without_success_counts(self):
        for xml, missing in ((None, True), ("<testsuites>", False), ("<testsuites />", False)):
            with self.subTest(xml=xml, missing=missing):
                result, output, step_summary = self.run_report(xml, missing=missing)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("No test results are available.", output.read_text(encoding="utf-8"))
                self.assertIn("No test results are available.", step_summary.read_text(encoding="utf-8"))
                self.assertNotIn("PASSED", result.stdout)

    def test_tests_without_question_properties_get_honest_fallback(self):
        result, output, _ = self.run_report(
            '<testsuites><testsuite><testcase classname="contract" name="shape" /></testsuite></testsuites>'
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("No prompt metadata (see test method)", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
