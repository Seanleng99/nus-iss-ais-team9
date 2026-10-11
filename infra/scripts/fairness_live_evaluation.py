"""Repeated, synthetic, end-to-end fairness pairs with independent correctness checks.

Reuse the owned fixture, usage accounting and cleanup boundaries of live_evaluation.
Objective pass is separate from pending human review of explanation quality.
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
from pathlib import Path

from infra.scripts.live_evaluation import run_live_evaluation

FIELDS = {
    "selected_agents", "blocked", "dependency_capabilities", "needs_input_agents",
    "source_ids", "budget_data", "goal_data", "evidence_status",
}


def load_pairs(path):
    from app.evals.runner import validate_fairness_expectations

    pairs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not pairs:
        raise ValueError("Fairness dataset is empty")
    seen = set()
    for pair in pairs:
        case_id = pair.get("id", "")
        if not isinstance(case_id, str) or not re.fullmatch(r"[a-z0-9_-]{1,80}", case_id) or case_id in seen:
            raise ValueError("Fairness pair IDs must be unique bounded codes")
        seen.add(case_id)
        if (pair.get("kind") != "fairness_pair" or pair.get("data_classification") != "synthetic"
                or len(pair.get("inputs", [])) != 2 or not pair.get("rubric")
                or not pair.get("compare") or not set(pair["compare"]) <= FIELDS
                or not isinstance(pair.get("expected"), dict)
                or "blocked" not in pair["expected"] or len(pair["expected"]) < 2):
            raise ValueError("Pairs require synthetic inputs, independent outcomes, known comparison fields and a rubric")
        validate_fairness_expectations(pair)
    return pairs


def run_fairness_evaluation(*, pairs, repeats, run_kwargs):
    from app.core.prompts import PromptCatalog
    from app.core.schemas import CoachResponse
    from app.evals.runner import _fairness_projection, _matches_expected

    samples = {}
    cases = []
    prompt_hash = PromptCatalog().content_hash
    for pair in pairs:
        for index, (side, request) in enumerate(zip(("A", "B"), pair["inputs"], strict=True)):
            cases.append({
                "id": pair["id"] + "-" + side.lower(), "category": pair["dimension"],
                "pair_id": pair["id"], "side": side, "request": request,
                "expected": {**pair["expected"], **pair.get("side_expected", [{}, {}])[index]},
                "rubric": pair["rubric"], "compare": pair["compare"],
            })

    def independent_checks(response, expected):
        try:
            passed = _matches_expected(CoachResponse.model_validate(response), expected)
        except (ValueError, TypeError, KeyError):
            passed = False
        return [{"check": "fairness_independent_correctness", "passed": passed}]

    def observe(case, request, response, repeat, passed):
        parsed = CoachResponse.model_validate(response)
        audit = parsed.audit
        identity = {
            key: audit.get(key) for key in (
                "model_provider", "model_id", "prompt_set_version", "prompt_content_hash", "build_commit",
            )
        }
        identity_passed = (
            identity["prompt_content_hash"] == prompt_hash
            and identity["build_commit"] not in {None, "", "unknown"}
            and identity["build_commit"] == run_kwargs["commit_sha"]
        )
        samples[(case["pair_id"], repeat, case["side"])] = {
            "side": case["side"], "independent_correctness_passed": bool(passed),
            "identity_passed": identity_passed, "identity": identity,
            "trace_id": audit.get("trace_id"), "question": request["message"], "answer": parsed.answer,
            "projection": {field: _fairness_projection(parsed, field) for field in case["compare"]},
            "corpus_versions": {
                "education": sorted({
                    source.corpus_version for source in parsed.sources if source.corpus_version
                }),
                "policy": sorted({
                    str(source["corpus_version"]) for source in audit.get("policy_sources", [])
                    if source.get("corpus_version")
                }),
            },
        }

    live = run_live_evaluation(
        cases=cases, repeats=repeats, response_checks=independent_checks,
        response_observer=observe, **run_kwargs,
    )
    execution_passes = {(r["case_id"], r["repeat"]): r["passed"] for r in live["records"]}
    records = []
    for repeat in range(1, repeats + 1):
        for pair in pairs:
            sides = [samples.get((pair["id"], repeat, side)) for side in ("A", "B")]
            complete = all(side is not None for side in sides)
            checks = {
                "both_responses_captured": complete,
                "execution_and_cleanup": all(execution_passes.get((pair["id"] + "-" + side, repeat), False)
                                             for side in ("a", "b")),
                "independent_correctness": complete and all(s["independent_correctness_passed"] for s in sides),
                "same_deployment_and_prompt": complete and all(s["identity_passed"] for s in sides)
                and sides[0]["identity"] == sides[1]["identity"],
                "same_corpus_versions": complete and sides[0]["corpus_versions"] == sides[1]["corpus_versions"],
                "structural_consistency": complete and sides[0]["projection"] == sides[1]["projection"],
            }
            records.append({
                "pair_id": pair["id"], "dimension": pair["dimension"], "repeat": repeat,
                "passed": all(checks.values()), "checks": checks, "sides": sides, "rubric": pair["rubric"],
            })
    identities = {json.dumps(sample["identity"], sort_keys=True) for sample in samples.values()}
    # Different tasks legitimately retrieve different subsets of one approved corpus.
    observed_corpora = {family: set() for family in ("education", "policy")}
    for sample in samples.values():
        for family, versions in sample["corpus_versions"].items():
            observed_corpora[family].update(versions)
    dimensions = {}
    for dimension in sorted({p["dimension"] for p in pairs}):
        group = [r for r in records if r["dimension"] == dimension]
        dimensions[dimension] = {
            "passed": sum(r["passed"] for r in group), "total": len(group),
            "pass_rate": sum(r["passed"] for r in group) / len(group),
        }
    token_limit = run_kwargs.get("maximum_total_tokens")
    cost_limit = run_kwargs.get("maximum_estimated_cost_usd")
    fixture = run_kwargs.get("expected_model_provider") == "local_fixture"
    objective_passed = (
        live["completed_requested_runs"] and not live.get("usage_unknown")
        and (fixture or live["token_usage_complete"]) and live["pass_rate"] == 1
        and len(identities) == 1 and all(len(versions) <= 1 for versions in observed_corpora.values())
        and all(r["passed"] for r in records)
        and (token_limit is None or live["token_usage"]["total"] <= token_limit)
        and (cost_limit is None or live["cost_estimate"]["estimated_total"] <= cost_limit)
    )
    return {
        "schema_version": 1, "measurement": live["measurement"],
        "data_classification": "synthetic", "generated_at": live["generated_at"],
        "prompt_content_hash": prompt_hash, "objective_passed": bool(objective_passed),
        "observed_corpus_versions": {family: sorted(versions) for family, versions in observed_corpora.items()},
        "human_review_status": "pending", "fairness_acceptance": "not_established",
        "limitations": [
            "Synthetic authored pairs are not representative-user fairness evidence.",
            "Repeated generations share scenarios and are not independent population samples.",
            "Structural parity does not establish equal explanation quality; human review is pending.",
            "This initial dataset covers single-turn requests, not all conversational histories.",
        ],
        "requested_pairs": len(records), "passed_pairs": sum(r["passed"] for r in records),
        "dimension_results": dimensions, "pairs": records, "execution": live,
    }


def write_review_csv(report, path):
    """Randomize pair order; omit model identity and automated verdicts from review."""
    rows = []
    for pair in report["pairs"]:
        for sample in pair["sides"]:
            if sample:
                rows.append({
                    "pair_id": pair["pair_id"], "repeat": pair["repeat"], "side": sample["side"],
                    "question": sample["question"], "answer": sample["answer"],
                    "criteria": " | ".join(pair["rubric"]),
                    "correctness_1_to_5": "", "helpfulness_1_to_5": "", "respect_1_to_5": "",
                    "uncertainty_1_to_5": "", "unsupported_assumption": "", "reviewer_notes": "",
                })
    random.Random(0).shuffle(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["pair_id"])
        writer.writeheader()
        # Keep generated content literal when a reviewer opens the CSV in a spreadsheet.
        writer.writerows({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                          else value for key, value in row.items()} for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--api-key-env", default="BACKEND_API_KEY")
    parser.add_argument("--cases", type=Path, default=Path("apps/ai-service/app/evals/datasets/fairness_consistency.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--expected-model-provider", choices=["openai", "local_fixture"], default="openai")
    parser.add_argument("--expected-model-id", required=True)
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--output-cost-per-million", type=float, required=True)
    parser.add_argument("--maximum-estimated-cost-usd", type=float, default=1)
    parser.add_argument("--maximum-total-tokens", type=int, default=1000000)
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA", "local-working-tree"))
    args = parser.parse_args()
    if (args.repeats < 1 or args.timeout_seconds <= 0 or args.maximum_total_tokens < 1
            or args.maximum_estimated_cost_usd <= 0 or args.input_cost_per_million < 0
            or args.output_cost_per_million < 0):
        parser.error("Counts, timeouts and budgets must be positive; token rates must be nonnegative")
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        parser.error("The backend service key environment variable is required")
    from app.core.prompts import CURRENT_PROMPT_VERSION
    pairs = load_pairs(args.cases)
    report = run_fairness_evaluation(pairs=pairs, repeats=args.repeats, run_kwargs={
        "url": args.url, "api_key": api_key, "timeout_seconds": args.timeout_seconds,
        "expected_model_provider": args.expected_model_provider, "expected_model_id": args.expected_model_id,
        "expected_prompt_version": CURRENT_PROMPT_VERSION,
        "input_cost_per_million": args.input_cost_per_million,
        "output_cost_per_million": args.output_cost_per_million, "commit_sha": args.commit_sha,
        "maximum_estimated_cost_usd": None if args.expected_model_provider == "local_fixture" else args.maximum_estimated_cost_usd,
        "maximum_total_tokens": None if args.expected_model_provider == "local_fixture" else args.maximum_total_tokens,
    })
    report["dataset_sha256"] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_review_csv(report, args.review_output)
    print(json.dumps({key: report[key] for key in (
        "measurement", "objective_passed", "human_review_status", "requested_pairs", "passed_pairs",
    )}))
    if not report["objective_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
