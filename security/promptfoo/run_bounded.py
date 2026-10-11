"""Run the same project cases/grader with repeated trials and a live token cap."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from provider import EvaluationBudget, ProjectProvider

HERE = Path(__file__).resolve().parent
GRADE_SCRIPT = """
const fs = require('node:fs');
const { securityGrade } = require(process.argv[1]);
const { response, test } = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(securityGrade(response.output, {providerResponse: response, test})));
"""


def grade(response, case, expected_hash=None):
    if expected_hash is not None and hashlib.sha256((HERE / "assertions.cjs").read_bytes()).hexdigest() != expected_hash:
        raise RuntimeError("The grader changed during evaluation; start a fresh run")
    result = subprocess.run(["node", "-e", GRADE_SCRIPT, str(HERE / "assertions.cjs")],
        input=json.dumps({"response": response, "test": case}), capture_output=True,
        text=True, encoding="utf-8", timeout=15, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=2)
    parser.add_argument("--max-model-tokens", type=int, default=500000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-pattern", help="Select case descriptions for an explicitly scoped follow-up")
    parser.add_argument("--env-file", type=Path, help="Optional local credential file; only OPENAI_API_KEY is read")
    args = parser.parse_args()
    if not 50000 <= args.max_model_tokens <= 2000000:
        parser.error("--max-model-tokens must be between 50000 and 2000000")
    os.environ["PROMPTFOO_MODEL_MODE"] = args.mode
    if args.mode == "live":
        os.environ["RUN_LIVE_INVESTMENT_TESTS"] = "1"
        if args.env_file is not None:
            key = dotenv_values(args.env_file).get("OPENAI_API_KEY")
            if not key:
                parser.error("The credential file must contain OPENAI_API_KEY")
            os.environ["OPENAI_API_KEY"] = key
    cases_bytes = (HERE / "cases.json").read_bytes()
    cases = json.loads(cases_bytes)
    if args.case_pattern:
        pattern = re.compile(args.case_pattern)
        cases = [case for case in cases if pattern.search(case["description"])]
        if not cases:
            parser.error("--case-pattern selected no cases")
    grader_hash = hashlib.sha256((HERE / "assertions.cjs").read_bytes()).hexdigest()
    planned = sum(len(case["providers"]) for case in cases) * args.repeats
    budget = EvaluationBudget(args.max_model_tokens) if args.mode == "live" else None
    results = []
    payload = {"evaluation": {"started_at": datetime.now(UTC).isoformat(), "mode": args.mode,
        "test_commit": os.getenv("RELEASE_SHA") or os.getenv("GITHUB_SHA"),
        "repeats": args.repeats, "planned_cases": planned, "complete": False,
        "case_sha256": hashlib.sha256(cases_bytes).hexdigest(),
        "case_pattern": args.case_pattern,
        "grader_sha256": grader_hash,
        "max_model_tokens": args.max_model_tokens if budget else None,
        "retrieval": "governed_local_documents" if budget else "offline_fixture"},
        "results": {"results": results}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stopped = False
    for trial in range(1, args.repeats + 1):
        for case in cases:
            for target in case["providers"]:
                response = ProjectProvider(target, budget).call_api(case["vars"]["question"],
                    context={"vars": case["vars"]})
                grading = grade(response, case, grader_hash)
                results.append({"testCase": {**case, "metadata": {**case.get("metadata", {}), "trial": trial}},
                    "provider": {"label": target}, "response": response,
                    "success": grading["pass"], "gradingResult": grading})
                if budget:
                    payload["evaluation"].update(charged_tokens=budget.used + budget.reserved,
                        inflight_reserved_tokens=budget.reserved,
                        usage_complete=not budget.usage_unknown and budget.reserved == 0,
                        budget_exhausted=budget.exhausted)
                args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"{len(results)}/{planned} trial={trial} target={target} "
                      f"case={case['description']} pass={grading['pass']}", flush=True)
                if budget and (budget.exhausted or budget.usage_unknown or budget.reserved > 0):
                    stopped = True
                    break
            if stopped:
                break
        if stopped:
            break
    payload["evaluation"].update(complete=len(results) == planned and not stopped,
        completed_cases=len(results), finished_at=datetime.now(UTC).isoformat())
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["evaluation"]["complete"] and all(row["success"] for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
