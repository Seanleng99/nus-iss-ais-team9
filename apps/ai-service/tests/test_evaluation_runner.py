import json
from pathlib import Path

from app.core.config import Settings
from app.core.schemas import CoachRequest
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
    dataset = Path("app/evals/datasets/fairness_consistency.jsonl")

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
