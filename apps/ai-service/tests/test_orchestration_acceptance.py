"""Evaluation must reject plausible prose when routing or evidence is wrong."""

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.schemas import CoachResponse
from app.evals.orchestration_acceptance import assess, load_suite, run_suite

SUITE = Path("app/evals/datasets/orchestration_live_regression_v1.json")


def response():
    return CoachResponse(session_id="test", selected_agents=["budget", "spending"],
        answer="A plausible answer", agent_results=[
            {"agent": "budget", "summary": "Capacity", "rationale": [], "confidence": 1, "data": {"savings": 950}}],
        disclaimers=[], sources=[], audit={"answer_status": "answered", "events": [
            {"event_type": "task.created", "task_id": "b", "details": {"agent": "budget"}},
            {"event_type": "task.created", "task_id": "s", "details": {"agent": "spending"}},
            {"event_type": "compliance.completed", "details": {}}],
            "dependency_edges": [{"requester_task_id": "b", "provider_task_id": "s", "capability": "transaction_category_totals"}]})


def test_wrong_dependency_amount_and_missing_parallel_evidence_fail_even_with_an_answer():
    result = assess(response(), {"agent_sets": [["budget", "spending"]], "no_specialist_edges": True,
        "parallel_pairs": [["budget", "spending"]],
        "facts": [{"agent": "budget", "path": "savings", "value": 1600}]})
    assert not result["checks_passed"]
    assert set(result["failures"]) == {"UNEXPECTED_SPECIALIST_EDGE", "NO_OBSERVED_OVERLAP:budget/spending", "FACT:budget/savings"}
    assert result["evidence"]["content_review"] == "required"


def test_withheld_answer_and_unknown_owner_cannot_pass_acceptance():
    value = response()
    value.blocked = True
    value.audit["events"] = []
    result = assess(value, {"required_edges": [["budget", "spending", "transaction_category_totals"]]})
    assert not result["checks_passed"]
    assert "WITHHELD" in result["failures"] and "NO_INDEPENDENT_REVIEW" in result["failures"]
    assert result["evidence"]["edges"][0][0] == "unknown"


def test_frozen_suite_has_all_approved_turns_without_specialist_overrides():
    suite = load_suite(SUITE)
    assert len(suite["cases"]) == 34
    assert next(c for c in suite["cases"] if c["id"] == "26b")["previous_case"] == "26a"
    assert not any(c.get("input", {}).get("requested_agents") for c in suite["cases"])


def test_fixture_evaluation_is_labelled_and_never_claims_semantic_acceptance(tmp_path):
    suite = load_suite(SUITE)
    suite["cases"] = [next(c for c in suite["cases"] if c["id"] == "3")]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    result = run_suite(path, config=Settings(MODEL_PROVIDER="local_fixture"), repeats=2, build_commit="test")
    assert result["measurement"] == "offline_fixture_contract" and result["checked"] == 2
    # The legacy offline router adds Budget for this wording. Preserve that
    # failure rather than tailoring the fixture to the frozen expected route.
    assert result["checks_passed"] == 0
    assert all("AGENT_SET" in row["failures"] for row in result["results"])
    assert result["acceptance"] == "pending_content_review"


def test_suite_rejects_explicit_agent_override(tmp_path):
    suite = load_suite(SUITE)
    suite["cases"][0]["input"]["requested_agents"] = ["spending"]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite), encoding="utf-8")
    with pytest.raises(ValueError, match="overrides"):
        load_suite(path)


def test_updated_suite_separates_valid_decomposition_from_explicit_chain_demo():
    historical = load_suite(SUITE)
    current = load_suite(SUITE.with_name("orchestration_live_regression_v2.json"))
    assert len(current["cases"]) == 35
    before = next(case for case in historical["cases"] if case["id"] == "7")
    reasoning = next(case for case in current["cases"] if case["id"] == "7")
    demo = next(case for case in current["cases"] if case["id"] == "35")
    assert before["input"] == reasoning["input"]
    assert len(reasoning["expected"]["required_edges"]) == 1
    assert demo["expected"]["required_edges"] == before["expected"]["required_edges"]
    assert "reconcile" in demo["input"]["message"].lower()
