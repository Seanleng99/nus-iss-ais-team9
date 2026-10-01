import importlib.util
from datetime import date
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "ecr_scan_gate.py"
SPEC = importlib.util.spec_from_file_location("ecr_scan_gate", MODULE_PATH)
ecr_scan_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ecr_scan_gate)


def test_blocking_findings_summarizes_enhanced_inspector_result() -> None:
    response = {
        "imageScanFindings": {
            "enhancedFindings": [
                {
                    "severity": "HIGH",
                    "fixAvailable": "YES",
                    "sourceUrl": "https://example.test/CVE-2026-0001",
                    "packageVulnerabilityDetails": {
                        "vulnerabilityId": "CVE-2026-0001",
                        "vulnerablePackages": [
                            {
                                "name": "sample-package",
                                "version": "1.0",
                                "fixedInVersion": "1.1",
                                "packageManager": "OS",
                            }
                        ],
                    },
                }
            ]
        }
    }

    assert ecr_scan_gate.blocking_findings(response) == [
        {
            "severity": "HIGH",
            "id": "CVE-2026-0001",
            "fix_available": "YES",
            "source": "https://example.test/CVE-2026-0001",
            "packages": [
                {
                    "name": "sample-package",
                    "version": "1.0",
                    "fixed_in_version": "1.1",
                    "package_manager": "OS",
                }
            ],
            "attributes": {},
        }
    ]


def test_blocking_findings_summarizes_basic_ecr_result_and_ignores_medium() -> None:
    response = {
        "imageScanFindings": {
            "findings": [
                {
                    "severity": "HIGH",
                    "name": "CVE-2026-0002",
                    "uri": "https://example.test/CVE-2026-0002",
                    "attributes": [
                        {"key": "package_name", "value": "sample-library"},
                        {"key": "package_version", "value": "2.0"},
                        {"key": "fixed_version", "value": "2.1"},
                    ],
                },
                {"severity": "MEDIUM", "name": "CVE-2026-0003"},
            ]
        }
    }

    assert ecr_scan_gate.blocking_findings(response) == [
        {
            "severity": "HIGH",
            "id": "CVE-2026-0002",
            "fix_available": None,
            "source": "https://example.test/CVE-2026-0002",
            "packages": [],
            "attributes": {
                "package_name": "sample-library",
                "package_version": "2.0",
                "fixed_version": "2.1",
            },
        }
    ]


def test_exception_requires_exact_version_repository_and_unexpired_review(tmp_path) -> None:
    exception_file = tmp_path / "exceptions.json"
    exception_file.write_text(
        """{
  "exceptions": [{
    "id": "CVE-2026-14456",
    "package_name": "openssl",
    "package_version": "3.0.20-1~deb12u2",
    "repositories": ["demo-ai"],
    "reviewed_on": "2026-08-19",
    "reviewed_by": "Security owner",
    "expires_on": "2026-09-18",
    "reason": "Affected code was introduced in OpenSSL 3.5.",
    "source": "https://www.cve.org/CVERecord?id=CVE-2026-14456"
  }]
}
""",
        encoding="utf-8",
    )
    finding = {
        "id": "CVE-2026-14456",
        "attributes": {
            "package_name": "openssl",
            "package_version": "3.0.20-1~deb12u2",
        },
    }

    active = ecr_scan_gate.load_exceptions(exception_file, date(2026, 8, 19))

    assert ecr_scan_gate.excepted_finding(finding, "demo-ai", active) == active[0]
    assert ecr_scan_gate.excepted_finding(finding, "another-repository", active) is None
    assert ecr_scan_gate.load_exceptions(exception_file, date(2026, 9, 19)) == []


def test_exception_rejects_missing_or_overlong_review(tmp_path) -> None:
    exception_file = tmp_path / "exceptions.json"
    exception_file.write_text(
        """{
  "exceptions": [{
    "id": "CVE-2026-14456",
    "package_name": "openssl",
    "package_version": "3.0.20-1~deb12u2",
    "repositories": ["demo-ai"],
    "reviewed_on": "2026-08-19",
    "expires_on": "2026-09-19",
    "reason": "Affected code was introduced in OpenSSL 3.5.",
    "source": "https://www.cve.org/CVERecord?id=CVE-2026-14456"
  }]
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="reviewed_by"):
        ecr_scan_gate.load_exceptions(exception_file, date(2026, 8, 19))

    text = exception_file.read_text(encoding="utf-8")
    exception_file.write_text(
        text.replace(
            '"reviewed_on": "2026-08-19",',
            '"reviewed_on": "2026-08-19",\n    "reviewed_by": "Security owner",',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cannot exceed 30 days"):
        ecr_scan_gate.load_exceptions(exception_file, date(2026, 8, 19))


def test_describe_findings_forces_utf8_aws_cli_output(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured.update(kwargs)
        return ecr_scan_gate.subprocess.CompletedProcess(
            command,
            0,
            stdout='{"imageScanStatus":{"status":"COMPLETE"}}',
            stderr="",
        )

    monkeypatch.setattr(ecr_scan_gate.subprocess, "run", fake_run)

    response = ecr_scan_gate.describe_findings("demo-ai", "immutable-tag")

    assert response == {"imageScanStatus": {"status": "COMPLETE"}}
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"


def test_approved_gcc_exception_is_limited_to_repositories_version_and_review_window() -> None:
    exception_file = Path(__file__).parents[2] / "llmsecops" / "ecr-scan-exceptions.json"
    finding = {
        "id": "CVE-2026-102010",
        "attributes": {"package_name": "gcc-14", "package_version": "14.2.0-19"},
    }
    active = ecr_scan_gate.load_exceptions(exception_file, date(2026, 10, 1))
    approved = ecr_scan_gate.excepted_finding(finding, "nus-iss-ais-team9-ai", active)
    assert approved is not None
    assert approved["expires_on"] == "2026-10-08"
    for repository in ("nus-iss-ais-team9-backend", "nus-iss-ais-team9-frontend"):
        assert ecr_scan_gate.excepted_finding(finding, repository, active) == approved
    assert ecr_scan_gate.excepted_finding(finding, "another-repository", active) is None
    other_cve = {**finding, "id": "CVE-2026-99999"}
    assert ecr_scan_gate.excepted_finding(other_cve, "nus-iss-ais-team9-frontend", active) is None
    for attribute, value in (("package_name", "gcc-15"), ("package_version", "14.2.0-20")):
        different = {**finding, "attributes": {**finding["attributes"], attribute: value}}
        assert ecr_scan_gate.excepted_finding(different, "nus-iss-ais-team9-ai", active) is None
    last_day = ecr_scan_gate.load_exceptions(exception_file, date(2026, 10, 8))
    assert ecr_scan_gate.excepted_finding(finding, "nus-iss-ais-team9-ai", last_day)
    expired = ecr_scan_gate.load_exceptions(exception_file, date(2026, 10, 9))
    assert ecr_scan_gate.excepted_finding(finding, "nus-iss-ais-team9-ai", expired) is None
