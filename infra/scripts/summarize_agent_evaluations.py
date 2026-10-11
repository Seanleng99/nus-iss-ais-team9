"""Combine offline evidence and identify optional post-deployment live evaluations."""
import argparse
import html
import json
import os
import shutil
from pathlib import Path
from urllib.parse import quote

try:
    from .agent_live_evaluation import SUITES, initial_report, questions, table_cell
except ImportError:
    from agent_live_evaluation import SUITES, initial_report, questions, table_cell

OFFLINE_CONTRACT_ARTIFACTS = {"platform": "agent-offline-platform", "shared": "shared-library-contracts"}


def collect(directory, *, live_requested, live_job_result, phase=None):
    reports = []
    for suite in SUITES:
        offline_path = directory / f"agent-offline-{suite}/artifacts/{suite}-evaluation.json"
        # upload-artifact may trim the common root depending on its path selection.
        candidates = list((directory / f"agent-offline-{suite}").rglob(f"{suite}-evaluation.json"))
        if len(candidates) == 1:
            offline_path = candidates[0]
        offline = json.loads(offline_path.read_text()) if offline_path.exists() else None
        reports.append({"suite": suite, "mode": "offline",
                        "status": "NOT RUN / MISSING EVIDENCE" if offline is None else "PASS" if offline.get("accepted") else "FAIL",
                        "evidence": offline})
        candidates = list((directory / f"agent-live-{suite}").rglob("report.json"))
        live = json.loads(candidates[0].read_text()) if len(candidates) == 1 else None
        if phase == "pre_deployment":
            status = "OPTIONAL — selected in Release to AWS; off by default"
        elif not live_requested:
            status = "SKIPPED — live not selected"
        elif live is None or live.get("status") == "NOT RUN":
            status = "NOT RUN / INCOMPLETE"
        else:
            status = live["status"]
        reports.append({"suite": suite, "mode": "live", "status": status, "live_job_conclusion": live_job_result, "evidence": live})
    for suite, artifact in OFFLINE_CONTRACT_ARTIFACTS.items():
        candidates = list((directory / artifact).rglob(f"{suite}-evaluation.json"))
        evidence = json.loads(candidates[0].read_text(encoding="utf-8")) if len(candidates) == 1 else None
        reports.append({"suite": suite, "mode": "offline",
                        "status": "NOT RUN / MISSING EVIDENCE" if evidence is None else "PASS" if evidence.get("accepted") else "FAIL",
                        "evidence": evidence})
    return reports


def render(reports):
    lines = ["# Agent and RAG evaluation report", "",
             "Offline acceptance precedes deployment. Live agent/RAG, fairness and security stages are optional and off by default in Release to AWS. Enabled stages require passing evidence; skipped stages provide no live acceptance evidence.",
             "Full synthetic questions, expected outputs, actual answers, checks and dataset definitions follow in report.json and index.html.", "",
             "| Component | Offline | Live |", "|---|---|---|"]
    for suite in SUITES:
        selected = {r["mode"]: r["status"] for r in reports if r["suite"] == suite}
        lines.append(f"| {suite} | {selected['offline']} | {selected['live']} |")
    for row in reports:
        if row["suite"] in OFFLINE_CONTRACT_ARTIFACTS:
            lines.append(f"| {row['suite']} contracts | {row['status']} | N/A — offline contracts |")
    for row in reports:
        lines += ["", f"## {row['suite']} — {row['mode']}", ""]
        report = row["evidence"]
        if row["mode"] == "offline":
            if report is None:
                lines.append("No readable evidence. This evaluation has not passed.")
                continue
            lines += ["Dataset: " + ", ".join(item["path"] for item in report["datasets"]),
                      "Metrics: " + "; ".join(report["metrics"]),
                      "Acceptance: " + "; ".join(report["acceptance_criteria"]),
                      "", "| Question | Expected | Result | Actual fixture/application response |", "|---|---|---|---|"]
            examples = [case for case in report["results"].get("cases", []) if case.get("question") not in (None, "", "N/A")]
            for case in examples:
                lines.append("| " + " | ".join(table_cell(case.get(k, "N/A")) for k in ("question", "expected", "outcome", "response")) + " |")
            lines.append("Other helper/validation tests have no conversational answer; all test rows remain in the JSON/JUnit artifacts.")
        else:
            report = report or initial_report(row["suite"])
            spec = report["specification"]
            lines += ["Dataset: " + ", ".join(spec["datasets"]), "Expected: " + spec["expected_outputs"],
                      "Metrics: " + "; ".join(spec["metrics"]), "Acceptance: " + "; ".join(spec["acceptance_criteria"]),
                      "", "| Question | Expected | Result | Actual model answer / Bedrock passage |", "|---|---|---|---|"]
            for question, expected, result in questions(report):
                status = "NOT RUN" if result is None else "PASS" if result["passed"] else "FAIL"
                actual = "No live response" if result is None else result.get("answer", result.get("results", "No live response"))
                lines.append("| " + " | ".join(map(table_cell, (question, expected, status, actual))) + " |")
    return "\n".join(lines) + "\n"



def render_html(reports):
    parts = ["<!doctype html><html lang='en'><meta charset='utf-8'><title>Agent evaluation report</title>",
             "<style>body{max-width:1180px;margin:36px auto;padding:0 24px;font:16px/1.55 system-ui;color:#182d40;background:#f8fafc}h1{font-size:32px}section{background:white;border:1px solid #dbe3ea;border-radius:10px;padding:22px;margin:24px 0}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;border-bottom:1px solid #dbe3ea;padding:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f9;padding:14px}summary{cursor:pointer;padding:10px}details{border-bottom:1px solid #dbe3ea}a{color:#165ca2}.note{background:#eaf2fb;padding:14px}</style>",
             "<h1>Agent and RAG evaluations</h1><p class='note'>Offline acceptance precedes deployment. Live agent/RAG, fairness and security stages are optional and off by default in Release to AWS. Enabled stages require passing evidence; skipped stages provide no live acceptance evidence. Synthetic test data only.</p>",
             "<table><tr><th>Component</th><th>Offline</th><th>Live</th></tr>"]
    for suite in SUITES:
        modes = {row["mode"]: row["status"] for row in reports if row["suite"] == suite}
        parts.append(f"<tr><td><a href='#{suite}-offline'>{suite}</a></td><td>{html.escape(modes['offline'])}</td><td><a href='#{suite}-live'>{html.escape(modes['live'])}</a></td></tr>")
    for row in reports:
        if row["suite"] in OFFLINE_CONTRACT_ARTIFACTS:
            parts.append(f"<tr><td><a href='#{row['suite']}-offline'>{row['suite']} contracts</a></td>"
                         f"<td>{html.escape(row['status'])}</td><td>N/A — offline contracts</td></tr>")
    parts.append("</table>")
    for row in reports:
        suite, mode = row["suite"], row["mode"]
        parts.append(f"<section id='{suite}-{mode}'><h2>{suite} · {mode}: {html.escape(row['status'])}</h2>")
        report = row["evidence"]
        if mode == "offline":
            if report is None:
                parts.append("<p>No readable evidence.</p></section>")
                continue
            spec = {key: report[key] for key in ("measurement", "datasets", "metrics", "acceptance_criteria", "limitations")}
            parts.append("<details><summary>Dataset, expected outputs, metrics and acceptance criteria</summary><pre>" + html.escape(json.dumps(spec, indent=2, ensure_ascii=False)) + "</pre></details>")
            for case in report["results"].get("cases", []):
                label = case["question"] if case["question"] != "N/A" else case["test_id"]
                parts.append("<details><summary>" + html.escape(case["outcome"].upper() + " · " + label) + "</summary><h3>Expected output</h3><pre>" + html.escape(case["expected"]) + "</pre><h3>Actual fixture/application response</h3><pre>" + html.escape(case["response"]) + "</pre><p>" + html.escape(case["reason"]) + "</p></details>")
        else:
            report = report or initial_report(suite)
            parts.append("<p>Test commit: " + html.escape(str(report.get("test_commit"))) + "; deployed commit: " + html.escape(str(report.get("deployed_commit", "not verified"))) + ".</p>")
            parts.append("<details><summary>Dataset, expected outputs, metrics and acceptance criteria</summary><pre>" + html.escape(json.dumps(report["specification"], indent=2, ensure_ascii=False)) + "</pre></details>")
            for question, expected, result in questions(report):
                status = "NOT RUN" if result is None else "PASS" if result["passed"] else "FAIL"
                actual = "No live response recorded" if result is None else result.get("answer", result.get("results", "No live response recorded"))
                parts.append("<details><summary>" + html.escape(status + " · " + question) + "</summary><h3>Expected output</h3><pre>" + html.escape(json.dumps(expected, indent=2, ensure_ascii=False)) + "</pre><h3>Actual model answer / Bedrock passage</h3><pre>" + html.escape(actual if isinstance(actual, str) else json.dumps(actual, indent=2, ensure_ascii=False)) + "</pre></details>")
            parts.append("<details><summary>Full execution evidence and checks</summary><pre>" + html.escape(json.dumps(report, indent=2, ensure_ascii=False)) + "</pre></details>")
        parts.append("</section>")
    parts.append("</html>")
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reports = collect(args.input, live_requested=os.getenv("LIVE_REQUESTED") == "true",
                      live_job_result=os.getenv("LIVE_JOB_RESULT", "unknown"),
                      phase=os.getenv("EVALUATION_PHASE"))
    args.output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(reports, indent=2, ensure_ascii=False)
    (args.output / "report.json").write_text(payload + "\n")
    markdown = render(reports)
    page = render_html(reports)
    jobs = json.loads(os.getenv("CI_JOB_RESULTS", "{}"))
    if jobs:
        rows = [{"job": name, "result": data["result"]} for name, data in jobs.items()]
        (args.output / "ci-jobs.json").write_text(json.dumps(rows, indent=2) + "\n")
        shutil.copytree(args.input, args.output / "evidence", dirs_exist_ok=True)
        overview_md, overview_html = ci_overview(rows, args.output / "evidence")
        markdown = overview_md + "\n" + markdown
        page = page.replace("<h1>Agent and RAG evaluations</h1>", overview_html + "<h1>Agent and RAG evaluations</h1>")
    (args.output / "summary.md").write_text(markdown)
    (args.output / "index.html").write_text(page)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        # A GitHub job summary is bounded. Full evidence is always in the artifact.
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(markdown[:700_000] + "\n\nFull unabridged evidence: agent-evaluation-report artifact.\n")


def ci_overview(jobs, evidence_directory):
    """One index for CI outcomes and retained detailed reports; never infer test passes."""
    note = "Job conclusions are separate from test acceptance. Failed or missing case evidence cannot establish acceptance; inspect the detailed reports below."
    lines = ["# CI and LLMSecOps report", "", note, "", "| Job | Conclusion |", "|---|---|"]
    parts = ["<h1>CI and LLMSecOps report</h1><p>" + note + "</p><table><tr><th>Job</th><th>Conclusion</th></tr>"]
    for row in jobs:
        lines.append(f"| {table_cell(row['job'])} | {table_cell(row['result'])} |")
        parts.append("<tr><td>" + html.escape(row["job"]) + "</td><td>" + html.escape(row["result"]) + "</td></tr>")
    security = next((row for row in jobs if row["job"] == "security-live"), None)
    if security:
        candidates = list(evidence_directory.rglob("promptfoo-live-status.json"))
        status = "SKIPPED" if security["result"] == "skipped" else "NOT RUN / INCOMPLETE"
        if len(candidates) == 1:
            status = json.loads(candidates[0].read_text())["status"]
        lines.append(f"| Live security acceptance (actual evidence) | {table_cell(status)} |")
        parts.append("<tr><td>Live security acceptance (actual evidence)</td><td>" + html.escape(status) + "</td></tr>")
    lines += ["", "## Detailed evidence", ""]
    parts.append("</table><h2>Detailed evidence</h2><ul>")
    for path in sorted(evidence_directory.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(evidence_directory).as_posix()
        url = "evidence/" + quote(name)
        lines.append(f"- [{table_cell(name)}]({url})")
        parts.append(f'<li><a href="{html.escape(url, quote=True)}">{html.escape(name)}</a></li>')
    parts.append("</ul>")
    return "\n".join(lines) + "\n", "\n".join(parts)


if __name__ == "__main__":
    main()
