from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "summarize_dependency_audit.py"

JINJA_REDOS = {
    "id": "PYSEC-2021-66",
    "fix_versions": ["2.11.3"],
    "aliases": ["GHSA-g3rq-g295-4j3m", "CVE-2020-28493"],
    "description": "ReDoS in the urlize filter.",
}
VULNERABLE_AUDIT = {
    "dependencies": [
        # pip-audit 2.10.1 can repeat one advisory for a package; count it once.
        {"name": "jinja2", "version": "2.11.2", "vulns": [JINJA_REDOS, JINJA_REDOS]},
        {
            "name": "legacy-lib",
            "version": "0.1",
            "vulns": [{"id": "GHSA-xxxx-yyyy-zzzz", "fix_versions": [], "aliases": [], "description": "No fix."}],
        },
        {"name": "requests", "version": "2.32.4", "vulns": []},
        {"name": "fastapi", "version": "0.115.0", "vulns": []},
        {"name": "private-wheel", "skip_reason": "Dependency not found on PyPI"},
    ],
    "fixes": [],
}
CLEAN_AUDIT = {
    "dependencies": [
        {"name": "streamlit", "version": "1.50.0", "vulns": []},
        {"name": "pandas", "version": "2.3.0", "vulns": []},
    ],
    "fixes": [],
}


class DependencyAuditSummaryTests(unittest.TestCase):
    def run_report(self, audits: dict[str, str | None]):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        paths = []
        for service, payload in audits.items():
            path = root / f"dependency-audit-{service}.json"
            if payload is not None:
                path.write_text(payload, encoding="utf-8")
            paths.append(str(path))
        output = root / "summary.md"
        env = os.environ.copy()
        env["GITHUB_STEP_SUMMARY"] = str(root / "step-summary.md")
        result = subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), *paths, "--output", str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        return result, output, root / "step-summary.md"

    def test_real_pip_audit_shape_reports_totals_services_and_findings(self):
        result, output, step_summary = self.run_report(
            {"backend": json.dumps(VULNERABLE_AUDIT), "frontend": json.dumps(CLEAN_AUDIT)}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = output.read_text(encoding="utf-8")
        self.assertEqual(step_summary.read_text(encoding="utf-8"), report + "\n")
        self.assertIn(
            "Audited 2 services and 6 resolved packages: 2 vulnerable packages, "
            "2 advisories (1 with a fix available), 1 skipped package.",
            report,
        )
        self.assertIn("| backend | 4 | 2 | 2 | 1 | 1 |", report)
        self.assertIn("| frontend | 2 | 0 | 0 | 0 | 0 |", report)
        self.assertIn(
            "| backend | jinja2 | 2.11.2 | PYSEC-2021-66 | GHSA-g3rq-g295-4j3m, CVE-2020-28493 | 2.11.3 |",
            report,
        )
        self.assertIn("| backend | legacy-lib | 0.1 | GHSA-xxxx-yyyy-zzzz |  | No fix available |", report)
        self.assertIn("| backend | private-wheel | Dependency not found on PyPI |", report)
        self.assertIn("Dependency audit: 2 vulnerable packages", result.stdout)

    def test_chart_shows_package_health_split(self):
        _, output, _ = self.run_report(
            {"backend": json.dumps(VULNERABLE_AUDIT), "frontend": json.dumps(CLEAN_AUDIT)}
        )

        report = output.read_text(encoding="utf-8")
        self.assertIn("```mermaid\npie showData", report)
        self.assertIn('"Clean" : 4', report)
        self.assertIn('"Vulnerable, fix available" : 1', report)
        self.assertIn('"Vulnerable, no fix" : 1', report)
        self.assertIn('"Skipped" : 1', report)

    def test_clean_audit_reports_no_known_vulnerabilities(self):
        result, output, _ = self.run_report({"ai-service": json.dumps(CLEAN_AUDIT)})

        self.assertEqual(result.returncode, 0, result.stderr)
        report = output.read_text(encoding="utf-8")
        self.assertIn("No known vulnerabilities were found.", report)
        self.assertIn('"Clean" : 2', report)
        self.assertNotIn('"Vulnerable', report)
        self.assertNotIn("| Service | Package | Installed | Advisory |", report)

    def test_missing_or_malformed_audit_is_reported_and_fails(self):
        result, output, _ = self.run_report(
            {"ai-service": None, "backend": "{not json", "frontend": json.dumps(CLEAN_AUDIT)}
        )

        self.assertEqual(result.returncode, 2)
        report = output.read_text(encoding="utf-8")
        self.assertIn("| ai-service | Audit results are missing or malformed. |", report)
        self.assertIn("| backend | Audit results are missing or malformed. |", report)
        self.assertIn("| frontend | 2 | 0 | 0 | 0 | 0 |", report)
        self.assertIn("missing or malformed", result.stderr)

    def test_advisory_text_cannot_inject_markdown_or_workflow_commands(self):
        hostile = {
            "dependencies": [
                {
                    "name": "evil",
                    "version": "1.0",
                    "vulns": [{
                        "id": "ID|`x`",
                        "fix_versions": ["2.0"],
                        "aliases": ["[link](http://x)"],
                        "description": "##[error]boom\n| broken |",
                    }],
                }
            ],
            "fixes": [],
        }
        result, output, _ = self.run_report({"backend": json.dumps(hostile)})

        report = output.read_text(encoding="utf-8")
        self.assertIn("ID&#124;&#96;x&#96;", report)
        self.assertIn("&#91;link&#93;(http://x)", report)
        self.assertNotIn("| broken |", report)
        self.assertNotIn("##[error]", result.stdout)

    def test_long_descriptions_are_shortened(self):
        audit = {
            "dependencies": [
                {
                    "name": "verbose",
                    "version": "1.0",
                    "vulns": [{"id": "PYSEC-1", "fix_versions": ["1.1"], "aliases": [], "description": "word " * 100}],
                }
            ],
            "fixes": [],
        }
        _, output, _ = self.run_report({"backend": json.dumps(audit)})

        row = next(line for line in output.read_text(encoding="utf-8").splitlines() if "PYSEC-1" in line)
        self.assertIn("…", row)
        self.assertLess(len(row), 400)


if __name__ == "__main__":
    unittest.main()
