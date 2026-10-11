import copy
import json
import sys
from pathlib import Path

import pytest

from infra.scripts import fairness_live_evaluation as fairness

ROOT = Path(__file__).resolve().parents[3]


def pair():
    return copy.deepcopy(fairness.load_pairs(
        ROOT / "apps/ai-service/app/evals/datasets/fairness_consistency.jsonl",
    )[0])


def capture(monkeypatch, *, wrong=False, unequal=False, stale=False, incomplete=False,
            usage_unknown=False, cleanup=False, expensive=False):
    from app.core.prompts import CURRENT_PROMPT_VERSION, PromptCatalog

    def fake_run(**kwargs):
        records = []
        for repeat in range(1, kwargs["repeats"] + 1):
            for case in kwargs["cases"]:
                if incomplete and case["side"] == "B":
                    continue
                data = {"disposable_income": 2800, "needs": 1400, "wants": 840, "savings": 560}
                if wrong or unequal and case["side"] == "B":
                    data["savings"] = 0
                response = {
                    "session_id": "synthetic", "selected_agents": ["budget"], "blocked": False,
                    "answer": "Synthetic budget explanation", "disclaimers": [], "sources": [],
                    "agent_results": [{"agent": "budget", "summary": "Budget", "rationale": ["Calculated"],
                                       "confidence": 0.8, "data": data}],
                    "audit": {"model_provider": "openai", "model_id": "generator",
                              "prompt_set_version": CURRENT_PROMPT_VERSION,
                              "prompt_content_hash": "stale" if stale else PromptCatalog().content_hash,
                              "build_commit": "test-build", "policy_sources": []},
                }
                checks = kwargs["response_checks"](response, case["expected"])
                kwargs["response_observer"](case, case["request"], response, repeat, all(c["passed"] for c in checks))
                records.append({"case_id": case["id"], "repeat": repeat, "passed": not cleanup})
        return {
            "records": records, "measurement": "live_generated_contract_checks", "generated_at": "test",
            "completed_requested_runs": not incomplete, "usage_unknown": usage_unknown,
            "token_usage_complete": not usage_unknown, "pass_rate": 0 if cleanup else 1,
            "token_usage": {"total": 10}, "cost_estimate": {"estimated_total": 2 if expensive else 0.01},
        }

    monkeypatch.setattr(fairness, "run_live_evaluation", fake_run)
    return fairness.run_fairness_evaluation(pairs=[pair()], repeats=2, run_kwargs={
        "commit_sha": "test-build", "maximum_total_tokens": 1000, "maximum_estimated_cost_usd": 1,
    })


def test_objective_pass_keeps_human_acceptance_pending(monkeypatch):
    report = capture(monkeypatch)
    assert report["objective_passed"] and report["passed_pairs"] == 2
    assert report["human_review_status"] == "pending"
    assert report["fairness_acceptance"] == "not_established"


@pytest.mark.parametrize("failure", [
    "wrong", "unequal", "stale", "incomplete", "usage_unknown", "cleanup", "expensive",
])
def test_matching_wrong_answers_or_incomplete_evidence_cannot_pass(monkeypatch, failure):
    assert not capture(monkeypatch, **{failure: True})["objective_passed"]


def test_review_export_omits_model_and_verdict_and_neutralizes_formulas(monkeypatch, tmp_path):
    report = capture(monkeypatch)
    report["pairs"][0]["sides"][0]["answer"] = "=unsafe_formula()"
    path = tmp_path / "review.csv"
    fairness.write_review_csv(report, path)
    content = path.read_text(encoding="utf-8-sig")
    assert "'=unsafe_formula()" in content
    assert "test-build" not in content and "objective_passed" not in content
    assert "unsupported_assumption" in content


@pytest.mark.parametrize("change", [
    {"data_classification": "real"}, {"expected": {}}, {"compare": ["unknown_field"]},
    {"side_expected": [{}]},
    {"expected": {"blocked": False, "misspelled_assertion": True}},
    {"side_expected": [{}, {"blocked": True}]},
])
def test_invalid_datasets_fail_before_endpoint_calls(tmp_path, change):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({**pair(), **change}), encoding="utf-8")
    with pytest.raises(ValueError):
        fairness.load_pairs(path)


def test_cli_defaults_to_all_19_pairs_once_and_plans_38_requests(monkeypatch, tmp_path):
    planned = {}

    def incomplete_execution(**kwargs):
        planned.update(kwargs)
        return {"records": [], "repeats": kwargs["repeats"],
                "requested_runs": len(kwargs["cases"]) * kwargs["repeats"],
                "measurement": "live_generated_contract_checks", "generated_at": "synthetic",
                "completed_requested_runs": False, "usage_unknown": False,
                "token_usage_complete": False, "pass_rate": 0,
                "token_usage": {"total": 0}, "cost_estimate": {"estimated_total": 0}}

    monkeypatch.setattr(fairness, "run_live_evaluation", incomplete_execution)
    monkeypatch.setenv("BACKEND_API_KEY", "synthetic-key")
    output = tmp_path / "fairness.json"
    monkeypatch.setattr(sys, "argv", ["fairness", "--url", "https://example.test/api/coach",
        "--expected-model-id", "gpt-6-luna", "--input-cost-per-million", "1",
        "--output-cost-per-million", "1", "--output", str(output),
        "--review-output", str(tmp_path / "review.csv")])
    with pytest.raises(SystemExit) as error:
        fairness.main()
    assert error.value.code == 1  # Missing actual responses still fail correctness.
    assert planned["repeats"] == 1 and len(planned["cases"]) == 38
    assert len({case["id"] for case in planned["cases"]}) == 38
    report = json.loads(output.read_text())
    assert report["requested_pairs"] == 19 and report["execution"]["requested_runs"] == 38
    assert len({(row["pair_id"], row["repeat"]) for row in report["pairs"]}) == 19
    assert {row["repeat"] for row in report["pairs"]} == {1}
