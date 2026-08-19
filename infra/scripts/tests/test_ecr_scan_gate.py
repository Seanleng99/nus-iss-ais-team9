import importlib.util
from pathlib import Path

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
