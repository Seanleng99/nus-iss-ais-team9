"""Combine offline and optional live evidence without disguising missing results."""
import argparse
import html
import json
import os
from pathlib import Path

try:
    from .agent_live_evaluation import SUITES, initial_report, questions, table_cell
except ImportError:
    from agent_live_evaluation import SUITES, initial_report, questions, table_cell


def collect(directory, *, live_requested, live_job_result):
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
        if not live_requested:
            status = "SKIPPED — live not selected"
        elif live is None or live.get("status") == "NOT RUN":
            status = "NOT RUN / INCOMPLETE"
        else:
            status = live["status"]
        reports.append({"suite": suite, "mode": "live", "status": status, "live_job_conclusion": live_job_result, "evidence": live})
    return reports


def render(reports):
    lines = ["# Agent and RAG evaluation report", "",
             "Offline acceptance is required. Live evaluations are optional and advisory; a successful workflow does not mean a failed or skipped live evaluation passed.",
             "Full synthetic questions, expected outputs, actual answers, checks and dataset definitions follow in report.json and index.html.", "",
             "| Component | Offline | Live |", "|---|---|---|"]
    for suite in SUITES:
        selected = {r["mode"]: r["status"] for r in reports if r["suite"] == suite}
        lines.append(f"| {suite} | {selected['offline']} | {selected['live']} |")
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
             "<h1>Agent and RAG evaluations</h1><p class='note'>Offline acceptance is required. Live evaluations are optional and advisory. A green workflow is not proof that a skipped or failed live evaluation passed. Synthetic test data only.</p>",
             "<table><tr><th>Component</th><th>Offline</th><th>Live</th></tr>"]
    for suite in SUITES:
        modes = {row["mode"]: row["status"] for row in reports if row["suite"] == suite}
        parts.append(f"<tr><td><a href='#{suite}-offline'>{suite}</a></td><td>{html.escape(modes['offline'])}</td><td><a href='#{suite}-live'>{html.escape(modes['live'])}</a></td></tr>")
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
                      live_job_result=os.getenv("LIVE_JOB_RESULT", "unknown"))
    args.output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(reports, indent=2, ensure_ascii=False)
    (args.output / "report.json").write_text(payload + "\n")
    markdown = render(reports)
    (args.output / "summary.md").write_text(markdown)
    (args.output / "index.html").write_text(render_html(reports))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        # A GitHub job summary is bounded. Full evidence is always in the artifact.
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
            handle.write(markdown[:700_000] + "\n\nFull unabridged evidence: agent-evaluation-report artifact.\n")


if __name__ == "__main__":
    main()
