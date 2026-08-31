from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ALLOWED_EVIDENCE_KINDS = {
    "architecture",
    "decision",
    "documentation",
    "evaluation",
    "implementation",
    "operations",
    "policy",
    "test",
    "workflow",
}
ALLOWED_REQUIREMENT_STATUSES = {"controlled", "implemented"}
REQUIRED_REQUIREMENT_IDS = {
    "ARCH-01",
    "AGENT-01",
    "COMM-01",
    "MODEL-01",
    "MEMORY-01",
    "TOOLS-01",
    "TRACE-01",
    "RAI-01",
    "SEC-01",
    "EVAL-01",
    "RAG-01",
    "IDENTITY-01",
    "CICD-01",
    "OPS-01",
    "LIFECYCLE-01",
}
REQUIRED_DEFERRED_IDS = {
    "DEFER-DR",
    "DEFER-DURABLE-MEMORY",
    "DEFER-MCP-A2A",
    "DEFER-PRODUCTION",
    "DEFER-REPRESENTATIVE-USERS",
}


class AssessmentValidationError(ValueError):
    """Raised when final-assessment evidence is incomplete or inconsistent."""


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssessmentValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _require_list(value: object, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise AssessmentValidationError(f"{field} must be a non-empty list")
    return value


def _unique_ids(items: list[Any], field: str) -> set[str]:
    identifiers: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise AssessmentValidationError(f"{field}[{index}] must be an object")
        identifiers.append(_require_string(item.get("id"), f"{field}[{index}].id"))
    if len(identifiers) != len(set(identifiers)):
        raise AssessmentValidationError(f"{field} contains duplicate ids")
    return set(identifiers)


def _resolve_evidence_path(repository_root: Path, raw_path: object) -> Path:
    path = PurePosixPath(_require_string(raw_path, "evidence.path"))
    if path.is_absolute() or ".." in path.parts:
        raise AssessmentValidationError(
            f"evidence path must remain repository-relative: {path}"
        )
    resolved_root = repository_root.resolve()
    resolved = resolved_root.joinpath(*path.parts).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise AssessmentValidationError(f"evidence path escapes repository: {path}")
    if not resolved.is_file():
        raise AssessmentValidationError(f"evidence file does not exist: {path}")
    return resolved


def _markdown_heading_anchors(content: str) -> set[str]:
    anchors: set[str] = set()
    for line in content.splitlines():
        if not line.startswith("## "):
            continue
        heading = line.removeprefix("## ").strip().lower()
        anchor = re.sub(r"[^a-z0-9]+", "-", heading).strip("-")
        if anchor:
            anchors.add(anchor)
    return anchors


def validate_manifest(manifest: dict[str, Any], repository_root: Path) -> list[Path]:
    if not isinstance(manifest, dict):
        raise AssessmentValidationError("manifest root must be an object")
    if manifest.get("schema_version") != 1:
        raise AssessmentValidationError("schema_version must be 1")

    project = manifest.get("project")
    if not isinstance(project, dict):
        raise AssessmentValidationError("project must be an object")
    _require_string(project.get("name"), "project.name")
    if project.get("data_classification") != "synthetic-data-only":
        raise AssessmentValidationError(
            "project.data_classification must remain synthetic-data-only"
        )
    _require_string(project.get("assessment_target"), "project.assessment_target")
    runbook_path = _resolve_evidence_path(
        repository_root, project.get("runbook_path")
    )
    runbook_anchors = _markdown_heading_anchors(
        runbook_path.read_text(encoding="utf-8")
    )

    requirements = _require_list(manifest.get("requirements"), "requirements")
    requirement_ids = _unique_ids(requirements, "requirements")
    missing_requirements = REQUIRED_REQUIREMENT_IDS - requirement_ids
    if missing_requirements:
        raise AssessmentValidationError(
            "missing required assessment requirements: "
            + ", ".join(sorted(missing_requirements))
        )

    scenarios = _require_list(manifest.get("demo_scenarios"), "demo_scenarios")
    scenario_ids = _unique_ids(scenarios, "demo_scenarios")
    for index, scenario in enumerate(scenarios):
        _require_string(scenario.get("name"), f"demo_scenarios[{index}].name")
        runbook_section = _require_string(
            scenario.get("runbook_section"),
            f"demo_scenarios[{index}].runbook_section",
        )
        if runbook_section not in runbook_anchors:
            raise AssessmentValidationError(
                f"demo scenario references missing runbook section: {runbook_section}"
            )
        expected = _require_list(
            scenario.get("expected_evidence"),
            f"demo_scenarios[{index}].expected_evidence",
        )
        for evidence_index, value in enumerate(expected):
            _require_string(
                value,
                f"demo_scenarios[{index}].expected_evidence[{evidence_index}]",
            )

    deferred = _require_list(manifest.get("deferred"), "deferred")
    deferred_ids = _unique_ids(deferred, "deferred")
    missing_deferred = REQUIRED_DEFERRED_IDS - deferred_ids
    if missing_deferred:
        raise AssessmentValidationError(
            "missing required scope decisions: " + ", ".join(sorted(missing_deferred))
        )
    for index, item in enumerate(deferred):
        _require_string(item.get("reason"), f"deferred[{index}].reason")
        _require_string(
            item.get("activation_condition"),
            f"deferred[{index}].activation_condition",
        )

    evidence_files: dict[str, Path] = {
        project["runbook_path"]: runbook_path,
    }
    covered_scenarios: set[str] = set()
    for index, requirement in enumerate(requirements):
        _require_string(requirement.get("name"), f"requirements[{index}].name")
        status = _require_string(
            requirement.get("status"), f"requirements[{index}].status"
        )
        if status not in ALLOWED_REQUIREMENT_STATUSES:
            raise AssessmentValidationError(
                f"requirements[{index}].status is not approved: {status}"
            )
        evidence = _require_list(
            requirement.get("evidence"), f"requirements[{index}].evidence"
        )
        for evidence_index, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise AssessmentValidationError(
                    f"requirements[{index}].evidence[{evidence_index}] must be an object"
                )
            kind = _require_string(
                item.get("kind"),
                f"requirements[{index}].evidence[{evidence_index}].kind",
            )
            if kind not in ALLOWED_EVIDENCE_KINDS:
                raise AssessmentValidationError(f"unsupported evidence kind: {kind}")
            raw_path = _require_string(
                item.get("path"),
                f"requirements[{index}].evidence[{evidence_index}].path",
            )
            evidence_files[raw_path] = _resolve_evidence_path(repository_root, raw_path)

        linked_scenarios = requirement.get("demo_scenarios", [])
        if not isinstance(linked_scenarios, list):
            raise AssessmentValidationError(
                f"requirements[{index}].demo_scenarios must be a list"
            )
        for scenario_id in linked_scenarios:
            normalized = _require_string(scenario_id, "requirement.demo_scenarios[]")
            if normalized not in scenario_ids:
                raise AssessmentValidationError(
                    f"requirement references unknown demo scenario: {normalized}"
                )
            covered_scenarios.add(normalized)

    uncovered_scenarios = scenario_ids - covered_scenarios
    if uncovered_scenarios:
        raise AssessmentValidationError(
            "demo scenarios are not linked to requirements: "
            + ", ".join(sorted(uncovered_scenarios))
        )
    return [evidence_files[path] for path in sorted(evidence_files)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_commit() -> str:
    github_sha = os.environ.get("GITHUB_SHA", "").strip()
    return github_sha or "local-working-tree"


def build_report(
    manifest_path: Path, repository_root: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    evidence_files = validate_manifest(manifest, repository_root)
    resolved_root = repository_root.resolve()
    file_evidence = [
        {
            "path": path.relative_to(resolved_root).as_posix(),
            "sha256": _sha256(path),
        }
        for path in evidence_files
    ]
    return {
        "schema_version": 1,
        "result": "pass",
        "generated_at": datetime.now(UTC).isoformat(),
        "repository_commit": _repository_commit(),
        "manifest": manifest_path.resolve().relative_to(resolved_root).as_posix(),
        "manifest_sha256": _sha256(manifest_path),
        "data_classification": manifest["project"]["data_classification"],
        "requirement_count": len(manifest["requirements"]),
        "demo_scenario_count": len(manifest["demo_scenarios"]),
        "deferred_decision_count": len(manifest["deferred"]),
        "evidence_file_count": len(file_evidence),
        "evidence_files": file_evidence,
    }


def render_markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "## Final assessment evidence",
            "",
            f"- Result: **{report['result'].upper()}**",
            f"- Commit: `{report['repository_commit']}`",
            f"- Data classification: `{report['data_classification']}`",
            f"- Requirements mapped: {report['requirement_count']}",
            f"- Demonstration scenarios: {report['demo_scenario_count']}",
            f"- Deferred scope decisions: {report['deferred_decision_count']}",
            f"- Integrity-hashed evidence files: {report['evidence_file_count']}",
            "",
            (
                "The report contains repository-relative paths and SHA-256 hashes only; "
                "it does not retain prompts, credentials, personal data, or financial "
                "records."
            ),
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and inventory final-assessment evidence"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("infra/llmsecops/final-assessment-manifest.json"),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise AssessmentValidationError("manifest root must be an object")
        report = build_report(args.manifest, args.repository_root, manifest)
    except (AssessmentValidationError, json.JSONDecodeError, OSError) as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
