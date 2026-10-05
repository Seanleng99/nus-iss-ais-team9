import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from language_fixtures import language_case

from app.core.config import Settings
from app.core.schemas import AgentName, CoachRequest
from app.evals.gate import evaluate_policy
from app.evals.runner import _matches_expected, run_dataset
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


def _orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
    )


def test_expected_properties_are_conjunctive() -> None:
    response = _orchestrator().handle(
        CoachRequest(
            user_id="eval",
            session_id="conjunctive",
            message="Create a monthly budget",
            requested_agents=["budget"],
            snapshot={"monthly_income": {"amount": 4000}},
        )
    )

    assert _matches_expected(
        response,
        {
            "selected_agents": ["budget"],
            "forbidden_agents": ["goal_strategy"],
            "blocked": False,
            "minimum_disclaimers": 1,
        },
    )
    assert not _matches_expected(
        response,
        {"selected_agents": ["budget"], "blocked": True},
    )


@pytest.mark.parametrize("data", [
    {}, {"savings": None}, {"savings": "unknown"}, {"savings": {}},
    {"savings": float("nan")}, {"savings": float("inf")}, {"savings": False},
])
def test_unavailable_or_invalid_budget_amount_fails_without_crashing(data) -> None:
    response = SimpleNamespace(
        agent_results=[SimpleNamespace(agent=AgentName.BUDGET, data=data)],
        blocked=False,
    )

    assert not _matches_expected(response, {"savings": 0})


def test_unavailable_budget_amount_is_recorded_as_failed_case(tmp_path: Path) -> None:
    request = {
        "user_id": "eval", "session_id": "unknown-recurrence",
        "message": "Create a monthly budget", "requested_agents": ["budget"],
        "snapshot": {
            "monthly_income": {"amount": 5000},
            "period_start": "2026-08-01",
            "recurring_expenses": [{
                "description": "Rent", "category": "housing",
                "amount": {"amount": 1500}, "occurred_on": "2026-08-01",
            }],
        },
    }
    dataset = tmp_path / "unavailable-budget.jsonl"
    cases = [
        {"id": "invented-savings", "input": request, "expected": {"savings": 700}},
        {"id": "unavailable-savings", "input": request, "expected": {"savings": None}},
    ]
    dataset.write_text(
        "".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8",
    )

    metrics = run_dataset(dataset)

    assert metrics["total"] == 2
    assert metrics["passed"] == 1
    assert metrics["failed_case_ids"] == ["invented-savings"]


def test_repository_evaluation_policy_passes(monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    monkeypatch.chdir(root)

    report, passed = evaluate_policy(root / "infra/llmsecops/evaluation-policy.json")

    assert passed, {
        suite["name"]: suite["metrics"]["failed_case_ids"]
        for suite in report["datasets"]
        if suite["metrics"]["failed_case_ids"]
    }


def test_chinese_answer_check_rejects_an_english_answer_with_chinese_metadata() -> None:
    response = _orchestrator().handle(
        CoachRequest(
            user_id="eval",
            session_id="language-check",
            message=language_case("evaluation_runner.response"),
            response_locale="zh-Hans",
            requested_agents=["investment_education"],
        )
    )
    assert _matches_expected(response, {"answer_language": "Chinese"})
    response.answer = "This is an English answer regardless of the Chinese language hint."
    assert not _matches_expected(response, {"answer_language": "Chinese"})


def test_dataset_evidence_includes_failed_case_ids(tmp_path: Path) -> None:
    dataset = tmp_path / "failed.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "wrong-route",
                "input": {
                    "user_id": "eval",
                    "session_id": "failed-case",
                    "message": "Create a monthly budget",
                    "requested_agents": ["budget"],
                    "snapshot": {"monthly_income": {"amount": 4000}},
                },
                "expected": {"selected_agents": ["spending"]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metrics = run_dataset(dataset)

    assert metrics["accuracy"] == 0
    assert metrics["failed_case_ids"] == ["wrong-route"]


def test_fairness_dataset_compares_structural_outcomes() -> None:
    dataset = (
        Path(__file__).resolve().parents[1]
        / "app/evals/datasets/fairness_consistency.jsonl"
    )

    metrics = run_dataset(dataset)

    assert metrics["fairness_consistency_rate"] == 1.0
    assert metrics["failed_case_ids"] == []


def test_policy_blocks_any_failed_case_when_accuracy_is_required(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "policy-failure.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "must-fail",
                "input": {
                    "user_id": "eval",
                    "session_id": "policy-failure",
                    "message": "Create a monthly budget",
                    "requested_agents": ["budget"],
                    "snapshot": {"monthly_income": {"amount": 4000}},
                },
                "expected": {"blocked": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "version": 1,
                "suites": [
                    {
                        "name": "strict",
                        "dataset": str(dataset),
                        "minimums": {"accuracy": 1.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report, passed = evaluate_policy(policy)

    assert passed is False
    assert report["datasets"][0]["metrics"]["failed_case_ids"] == ["must-fail"]
