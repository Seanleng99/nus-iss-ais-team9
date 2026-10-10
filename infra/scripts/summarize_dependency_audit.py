"""Render a Markdown report and chart from per-service pip-audit JSON results."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FILE_PREFIX = "dependency-audit-"
UNAVAILABLE = "Audit results are missing or malformed."
NO_FIX = "No fix available"
DESCRIPTION_LIMIT = 200
BAR_WIDTH = 10


@dataclass
class ServiceAudit:
    service: str
    packages: int = 0
    vulnerable: int = 0
    vulnerable_fixable: int = 0
    advisories: int = 0
    fixable_advisories: int = 0
    findings: list[dict[str, str]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


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
    return " ".join(_text(value).split()).replace("##[", "##\\[")


def _shorten(value: Any) -> str:
    text = " ".join(_text(value).split())
    if len(text) <= DESCRIPTION_LIMIT:
        return text
    return text[: DESCRIPTION_LIMIT - 1].rstrip() + "…"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _row(cells: list[Any]) -> str:
    return "| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |"


def _valid_vuln(vuln: Any) -> bool:
    return (
        isinstance(vuln, dict)
        and isinstance(vuln.get("id"), str)
        and isinstance(vuln.get("fix_versions", []), list)
    )


def _valid_dependency(dependency: Any) -> bool:
    if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str):
        return False
    if "skip_reason" in dependency:
        return True
    vulns = dependency.get("vulns")
    return (
        isinstance(dependency.get("version"), str)
        and isinstance(vulns, list)
        and all(_valid_vuln(vuln) for vuln in vulns)
    )


def _service_name(path: Path) -> str:
    return path.stem.removeprefix(FILE_PREFIX)


def _load(path: Path) -> ServiceAudit | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(dependencies, list) or not all(_valid_dependency(item) for item in dependencies):
        return None

    audit = ServiceAudit(_service_name(path))
    for dependency in dependencies:
        if "skip_reason" in dependency:
            audit.skipped.append({"package": dependency["name"], "reason": _text(dependency["skip_reason"])})
            continue
        audit.packages += 1
        # pip-audit can repeat an advisory for one package; report each advisory once.
        unique = {vuln["id"]: vuln for vuln in dependency["vulns"]}
        if not unique:
            continue
        audit.vulnerable += 1
        fixable = [vuln for vuln in unique.values() if vuln.get("fix_versions")]
        audit.advisories += len(unique)
        audit.fixable_advisories += len(fixable)
        if len(fixable) == len(unique):
            audit.vulnerable_fixable += 1
        for vuln in unique.values():
            fix_versions = [_text(version) for version in vuln.get("fix_versions") or []]
            audit.findings.append(
                {
                    "package": dependency["name"],
                    "version": dependency["version"],
                    "id": vuln["id"],
                    "aliases": ", ".join(_text(alias) for alias in vuln.get("aliases") or []),
                    "fix": ", ".join(fix_versions) or NO_FIX,
                    "description": _shorten(vuln.get("description")),
                }
            )
    return audit


def _bar(clean: int, total: int) -> str:
    filled = round(BAR_WIDTH * clean / total) if total else 0
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def _chart(audits: list[ServiceAudit]) -> list[str]:
    total = sum(audit.packages for audit in audits)
    slices = (
        ("Clean", total - sum(audit.vulnerable for audit in audits)),
        ("Vulnerable, fix available", sum(audit.vulnerable_fixable for audit in audits)),
        ("Vulnerable, no fix", sum(audit.vulnerable - audit.vulnerable_fixable for audit in audits)),
        ("Skipped", sum(len(audit.skipped) for audit in audits)),
    )
    if not any(count for _, count in slices):
        return []
    lines = ["```mermaid", "pie showData", f"    title Dependency health ({_plural(total, 'resolved package')})"]
    lines.extend(f'    "{label}" : {count}' for label, count in slices if count)
    lines.extend(("```", ""))
    return lines


def _report(title: str, audits: list[ServiceAudit], unavailable: list[str]) -> str:
    packages = sum(audit.packages for audit in audits)
    vulnerable = sum(audit.vulnerable for audit in audits)
    advisories = sum(audit.advisories for audit in audits)
    fixable = sum(audit.fixable_advisories for audit in audits)
    skipped = sum(len(audit.skipped) for audit in audits)
    lines = [
        f"## {_markdown_cell(title)}",
        "",
        (
            f"Audited {_plural(len(audits), 'service')} and {_plural(packages, 'resolved package')}: "
            f"{_plural(vulnerable, 'vulnerable package')}, "
            f"{_plural(advisories, 'advisory', 'advisories')} ({fixable} with a fix available), "
            f"{_plural(skipped, 'skipped package')}."
        ),
        "",
    ]
    if audits and not advisories:
        lines.extend(("No known vulnerabilities were found.", ""))
    lines.extend(_chart(audits))

    if audits:
        lines.extend(
            (
                "### Services",
                "",
                "| Service | Resolved packages | Vulnerable packages | Advisories | Fix available | Skipped | Clean share |",
                "|---|---|---|---|---|---|---|",
            )
        )
        for audit in audits:
            lines.append(
                _row(
                    [
                        audit.service,
                        audit.packages,
                        audit.vulnerable,
                        audit.advisories,
                        audit.fixable_advisories,
                        len(audit.skipped),
                        _bar(audit.packages - audit.vulnerable, audit.packages),
                    ]
                )
            )
        lines.append("")

    if unavailable:
        lines.extend(("### Unavailable audits", "", "| Service | Problem |", "|---|---|"))
        lines.extend(_row([service, UNAVAILABLE]) for service in unavailable)
        lines.append("")

    findings = [(audit.service, finding) for audit in audits for finding in audit.findings]
    if findings:
        lines.extend(
            (
                "### Vulnerabilities",
                "",
                "| Service | Package | Installed | Advisory | Aliases | Fix versions | Description |",
                "|---|---|---|---|---|---|---|",
            )
        )
        for service, finding in findings:
            lines.append(
                _row(
                    [
                        service,
                        *(finding[key] for key in ("package", "version", "id", "aliases", "fix", "description")),
                    ]
                )
            )
        lines.append("")

    skipped_rows = [(audit.service, item) for audit in audits for item in audit.skipped]
    if skipped_rows:
        lines.extend(("### Skipped packages", "", "| Service | Package | Skip reason |", "|---|---|---|"))
        lines.extend(_row([service, item["package"], item["reason"]]) for service, item in skipped_rows)
        lines.append("")

    lines.append(
        "pip-audit reports advisory identifiers and fix versions, not severity scores; "
        "the chart therefore groups packages by whether a fix is available."
    )
    return "\n".join(lines) + "\n"


def _publish(text: str, output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(text + "\n")


def summarize(paths: list[Path], title: str, output: Path | None) -> int:
    audits: list[ServiceAudit] = []
    unavailable: list[str] = []
    for path in paths:
        audit = _load(path)
        if audit is None:
            unavailable.append(_service_name(path))
        else:
            audits.append(audit)

    _publish(_report(title, audits, unavailable), output)
    for audit in audits:
        for finding in audit.findings:
            print(
                "Dependency audit finding: "
                + _console_line(f"{audit.service} {finding['package']} {finding['version']} {finding['id']}")
            )
    vulnerable = sum(audit.vulnerable for audit in audits)
    advisories = sum(audit.advisories for audit in audits)
    print(
        f"Dependency audit: {_plural(vulnerable, 'vulnerable package')} across "
        f"{_plural(len(audits), 'service')}; {_plural(advisories, 'advisory', 'advisories')}."
    )
    if unavailable:
        print(
            "Dependency audit summary: results are missing or malformed for "
            + _console_line(", ".join(unavailable)),
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit_json", type=Path, nargs="+", help="dependency-audit-<service>.json files")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--title", default="Dependency vulnerability audit")
    args = parser.parse_args()
    return summarize(args.audit_json, args.title, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
