"""Publish measured routing/RAG gates with their datasets and scoring contracts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

METRICS = {
    "accuracy": "Cases satisfying every expected invariant / all cases; not semantic answer quality.",
    "routing_accuracy": "Exact expected/actual agent-set matches / labeled routing cases, ignoring order.",
    "automatic_routing_accuracy": "Exact set matches for requests without requested_agents / automatic cases.",
    "override_accuracy": "Exact set matches for explicitly selected specialists / override cases.",
    "routing_precision": "Micro TP / (TP + FP); extra selected agents are false positives.",
    "routing_recall": "Micro TP / (TP + FN); missed expected agents are false negatives.",
    "routing_f1": "Harmonic mean of micro routing precision and recall; undefined denominators score zero.",
    "critical_block_rate": "Critical block-only cases satisfying all expected checks / critical block-only cases.",
    "source_recall_at_3": "Mean expected source-ID recall in the first three displayed response citations; not raw Bedrock ranking.",
    "evidence_gap_rate": "Expected-gap cases satisfying every expected check / expected-gap cases.",
    "security_control_rate": "Passing direct injection, PII, RAG injection and permission scenarios / security-control cases.",
    "dependency_accuracy": "Cases with the exact expected capability or missing-input outcome / dependency cases.",
    "policy_source_recall_at_3": "Mean expected Policy source-ID recall among the evaluator's retained Policy sources (at most three).",
    "budget_accuracy": "Cases satisfying all deterministic budget checks, including SGD 1 tolerance / budget cases.",
    "fairness_consistency_rate": "Pairs where both answers independently meet authored expectations and match specified structural outcomes / paired cases; not a demographic fairness guarantee.",
}


def cell(value, limit: int = 180) -> str:
    text = " ".join(str(value).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _json_cell(value) -> str:
    return cell(json.dumps(value, ensure_ascii=False, sort_keys=True))


def render(evaluation: dict, retrieval: dict) -> str:
    lines = [
        "## Investment, orchestrator and RAG evaluations", "",
        ("**Offline evidence only.** Routing uses LocalFixtureModelGateway. Passage relevance uses actual "
        "governed Markdown and the local retriever. Neither measures deployed OpenAI routing/answer quality "
        "or live AWS availability. API/Bedrock-adapter integration has its own JUnit report with stubbed transport."),
        "", ("Definitions for the seven agent suites and platform/shared contracts are in `infra/llmsecops/agent-evaluation-specs.json`; "
        "each suite publishes its dataset hashes, expected outputs, measured assertion rate and acceptance result."), "",
    ]
    for suite in evaluation["datasets"]:
        lines += [
            f"### {suite['name']}", "",
            f"Dataset: `{suite['dataset']}`. SHA-256: `{suite.get('dataset_sha256', 'not recorded')}`.",
            ("Expected outputs: the dataset's `expected` fields are checked conjunctively; `compare` fields "
            "define paired consistency. Routing expects agent labels; retrieval expects approved source IDs "
            "and gap behavior; safety expects block/redaction/permission outcomes. "
            "Beginner `answer_rubric` and `forbidden_behaviors` require separate human review and are not scored here."),
            "", (f"Cases: **{suite['metrics']['passed']}/{suite['metrics']['total']}**. "
            f"Failed IDs: `{', '.join(suite['metrics']['failed_case_ids']) or 'none'}`."), "",
            "| Metric | Definition | Actual | Acceptance | Result |",
            "| --- | --- | --- | --- | --- |",
        ]
        for check in suite["checks"]:
            requirement = (f">= {check['minimum']}" if check["check"] == "minimum"
                           else f"drop from {check['baseline']} <= {check['max_regression']}")
            lines.append(
                f"| {check['metric']} | {cell(METRICS.get(check['metric'], 'See versioned policy'))} | "
                f"{check['actual']} | {requirement} | {'PASS' if check['passed'] else 'FAIL'} |"
            )
        case_diagnostics = suite["metrics"].get("case_diagnostics", [])
        if case_diagnostics:
            lines += [
                "", "Case-level offline evidence (cells are shortened here; full values are in JSON):", "",
                "| Case | Type | Question / paired inputs | Expected output | Actual answer or value | Pass |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for item in case_diagnostics:
                if item.get("case_type") == "fairness_pair":
                    question = "; ".join(
                        f"{pair['side']}: {pair['question']}"
                        for pair in item.get("paired_inputs", [])
                    )
                else:
                    question = item.get("question", "N/A")
                actual = item.get("actual_answer", "N/A")
                if actual == "N/A":
                    actual = _json_cell(item.get("actual_output", "N/A"))
                lines.append(
                    f"| {cell(item.get('id', 'N/A'))} | {cell(item.get('case_type', 'N/A'))} | "
                    f"{cell(question)} | {_json_cell(item.get('expected_output', 'N/A'))} | "
                    f"{cell(actual)} | {item.get('passed', False)} |"
                )
        diagnostics = suite["metrics"].get("routing_case_diagnostics", [])
        if diagnostics:
            counts = suite["metrics"]["routing_confusion_totals"]
            lines += [
                "", (f"Routing TP/FP/FN: **{counts['tp']}/{counts['fp']}/{counts['fn']}**. "
                "Automatic and explicit-override cases remain separate below."), "",
                "| Case | Mode | Expected agents | Actual agents | Route correct | All invariants |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            lines.extend(
                f"| {cell(item['id'])} | {item['mode']} | {cell(', '.join(item['expected_agents']))} | "
                f"{cell(', '.join(item['actual_agents']))} | {item['routing_match']} | {item['overall_pass']} |"
                for item in diagnostics
            )
        lines.append("")
    lines += [
        "### Frozen passage retrieval relevance", "",
        ("Dataset: `apps/ai-service/app/evals/datasets/rag_evidence_v1.jsonl` (100 authored cases, "
        "English/Chinese, development/holdout grouped by topic family). Ground truth contains source IDs, "
        "exact required passages, expected grounded/partial/insufficient status and uncovered topics."),
        (f"Dataset SHA-256: `{retrieval['dataset_sha256']}`. Corpus: `{retrieval['corpus_version']}`. "
        f"Provider: `{retrieval['provider']}`. Split: `{retrieval['split']}`."), "",
        ("Expected output: the retrieved context contains each required source passage and preserves the "
        "exact evidence status/unanswered topics within 1,200 words. Passage recall uses the merged context "
        "from bounded retrieval queries (up to three results per query), not a global top-three document list."), "",
        "| Metric | Definition | Actual | Acceptance |",
        "| --- | --- | --- | --- |",
        f"| case_accuracy | All passage and scope checks pass / cases | {retrieval['case_accuracy']} | >= 0.99 |",
        f"| passage_recall_at_3 | Required passages found / required passages | {retrieval['passage_recall_at_3']} | >= 0.99 |",
        f"| scope_accuracy | Exact status and uncovered-topic match / cases | {retrieval['scope_accuracy']} | 1.0 |",
    ]
    for group in ("by_language", "by_status"):
        for label, value in retrieval[group].items():
            lines.append(f"| {group}.{label} | Complete-case pass rate in this slice | {value} | >= 0.99 when present |")
    lines += [
        "", "Case-level retrieved evidence (cells are shortened here; full passages are in JSON):", "",
        "| Case | Question | Expected output | Retrieved actual contexts | Pass |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {cell(item.get('id', 'N/A'))} | {cell(item.get('question', 'N/A'))} | "
        f"{_json_cell(item.get('expected_output', 'N/A'))} | "
        f"{_json_cell(item.get('retrieved_contexts', 'N/A'))} | {item['passed']} |"
        for item in retrieval["results"]
    )
    max_words = max((item["context_words"] for item in retrieval["results"]), default=0)
    failed = [item["id"] for item in retrieval["results"] if not item["passed"]]
    lines += [
        f"| max_context_words | Largest retrieved context | {max_words} | <= 1200 |", "",
        (f"Retrieval gate: **{'PASS' if retrieval['retrieval_gate_passed'] else 'FAIL'}**. "
        f"Cases: {retrieval['passed_cases']}/{retrieval['cases']}. Failed IDs: `{', '.join(failed) or 'none'}`."), "",
        ("Generated-answer correctness, explanation helpfulness and live-model routing accuracy: **not measured**. "
        "Numeric evaluation runs offline; the optional live evaluation job is selected separately."), "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--retrieval", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        evaluation = json.loads(args.evaluation.read_text())
        retrieval = json.loads(args.retrieval.read_text())
        if not evaluation["datasets"] or not retrieval["results"]:
            raise ValueError("Evaluation results are empty")
        markdown = render(evaluation, retrieval)
        passed = evaluation["passed"] and retrieval["retrieval_gate_passed"]
    except (OSError, ValueError, KeyError) as exc:
        markdown = f"## Investment evaluation incomplete\n\nRequired evidence is missing or invalid ({type(exc).__name__}). No passing result is claimed.\n"
        passed = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown)
    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
