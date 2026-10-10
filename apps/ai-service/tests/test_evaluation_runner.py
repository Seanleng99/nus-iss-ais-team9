import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from language_fixtures import language_case

from app.core.config import Settings
from app.core.schemas import AgentName, CoachRequest
from app.evals.gate import evaluate_policy
from app.evals.rag_evidence import evaluate as evaluate_rag_evidence
from app.evals.rag_evidence import load_cases as load_rag_cases
from app.evals.runner import _matches_expected, run_dataset
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
from app.rag.local_documents import (
    DEFAULT_CORPUS_ROOT,
    LocalDocumentEducationRetriever,
    load_documents,
)


def _orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
    )


def _stub_routing(monkeypatch, selected_by_session: dict[str, list[str]]) -> None:
    class StubOrchestrator:
        def __init__(self, **_kwargs):
            pass

        def handle(self, request):
            return SimpleNamespace(
                selected_agents=[
                    SimpleNamespace(value=name)
                    for name in selected_by_session[request.session_id]
                ],
                blocked=False,
                answer="stub response",
                sources=[],
                audit={},
                agent_results=[],
                disclaimers=[],
            )

    monkeypatch.setattr("app.evals.runner.AgentOrchestrator", StubOrchestrator)


def _write_routing_dataset(tmp_path: Path, cases: list[dict]) -> Path:
    dataset = tmp_path / "routing.jsonl"
    dataset.write_text(
        "".join(json.dumps(case) + "\n" for case in cases), encoding="utf-8",
    )
    return dataset


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
    for suite in report["datasets"]:
        metrics = suite["metrics"]
        assert len(metrics["case_diagnostics"]) == metrics["total"]
        assert all({"id", "case_type", "question", "expected_output", "actual_answer",
                    "actual_output", "passed"} <= item.keys()
                   for item in metrics["case_diagnostics"])
    guardrail = next(item for item in report["datasets"] if item["name"] == "guardrails")
    helper_case = guardrail["metrics"]["case_diagnostics"][0]
    assert helper_case["question"] == helper_case["test_input"]["text"]
    assert helper_case["actual_answer"] == "N/A"
    assert helper_case["actual_output"]["allowed"] is False
    fairness = next(item for item in report["datasets"] if item["name"] == "fairness-consistency")
    pair = fairness["metrics"]["case_diagnostics"][0]
    assert [item["side"] for item in pair["actual_output"]] == ["A", "B"]
    assert pair["actual_output"][0]["question"] != pair["actual_output"][1]["question"]
    conversation = next(item for item in report["datasets"] if item["name"] == "orchestrator")
    route = conversation["metrics"]["case_diagnostics"][0]
    assert route["question"] != "N/A" and route["actual_answer"] != "N/A"


def test_rag_evidence_rows_include_expected_and_retrieved_passages() -> None:
    dataset = Path(__file__).resolve().parents[1] / "app/evals/datasets/rag_evidence_v1.jsonl"
    _, documents = load_documents(
        DEFAULT_CORPUS_ROOT / "source_manifest.json", DEFAULT_CORPUS_ROOT / "documents",
    )
    cases = load_rag_cases(dataset, {source.source_id: text for source, text in documents})
    result = evaluate_rag_evidence(cases[:1], LocalDocumentEducationRetriever())["results"][0]

    assert result["question"] == cases[0].question
    assert result["expected_output"]["required_evidence"][0]["quote"] == cases[0].required_evidence[0].quote
    assert result["actual_answer"] == "N/A"
    assert result["retrieved_contexts"]
    assert result["retrieved_contexts"][0]["text"]
    assert result["passed"]


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


def test_routing_metrics_count_missed_extra_and_order_only_differences(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_routing(monkeypatch, {
        "missed": ["budget"],
        "extra": ["budget", "spending"],
        "order": ["investment_education", "spending"],
    })
    cases = [
        {"id": "missed", "input": {"user_id": "private", "session_id": "missed", "message": "x"},
         "expected": {"selected_agents": ["budget", "goal_strategy"]}},
        {"id": "extra", "input": {"user_id": "private", "session_id": "extra", "message": "x"},
         "expected": {"selected_agents": ["budget"]}},
        {"id": "order", "input": {"user_id": "private", "session_id": "order", "message": "x"},
         "expected": {"selected_agents": ["spending", "investment_education"]}},
    ]

    metrics = run_dataset(_write_routing_dataset(tmp_path, cases))

    assert metrics["routing_case_count"] == 3
    assert metrics["routing_confusion_totals"] == {"tp": 4, "fp": 1, "fn": 1}
    assert metrics["routing_precision"] == metrics["routing_recall"] == 0.8
    assert metrics["routing_f1"] == 0.8
    assert metrics["routing_accuracy"] == 0.3333
    assert metrics["accuracy"] == 0
    assert metrics["routing_case_diagnostics"][2]["routing_match"] is True
    assert metrics["routing_case_diagnostics"][2]["overall_pass"] is False
    assert {
        "id", "mode", "expected_agents", "actual_agents", "routing_match", "overall_pass",
    } <= metrics["routing_case_diagnostics"][0].keys()
    assert metrics["routing_case_diagnostics"][0]["question"] == "x"
    assert metrics["routing_case_diagnostics"][0]["actual_answer"] == "stub response"


def test_non_routing_safety_failure_does_not_change_route_accuracy(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_routing(monkeypatch, {"safety": ["budget"]})
    case = {
        "id": "safety", "input": {"user_id": "private", "session_id": "safety", "message": "x"},
        "expected": {"selected_agents": ["budget"], "blocked": True},
    }

    metrics = run_dataset(_write_routing_dataset(tmp_path, [case]))

    assert metrics["routing_accuracy"] == 1
    assert metrics["automatic_routing_accuracy"] == 1
    assert metrics["accuracy"] == 0


def test_automatic_routing_and_explicit_overrides_are_reported_separately(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_routing(monkeypatch, {"automatic": ["spending"], "override": ["budget"]})
    cases = [
        {"id": "automatic", "input": {"user_id": "private", "session_id": "automatic", "message": "x"},
         "expected": {"selected_agents": ["budget"]}},
        {"id": "override", "input": {"user_id": "private", "session_id": "override", "message": "x",
                                          "requested_agents": ["budget"]},
         "expected": {"selected_agents": ["budget"]}},
    ]

    metrics = run_dataset(_write_routing_dataset(tmp_path, cases))

    assert metrics["automatic_routing_case_count"] == 1
    assert metrics["explicit_override_case_count"] == 1
    assert metrics["automatic_routing_accuracy"] == 0
    assert metrics["override_accuracy"] == 1
    assert [item["mode"] for item in metrics["routing_case_diagnostics"]] == [
        "automatic", "explicit_override",
    ]


def test_empty_routing_prediction_cannot_have_perfect_f1(
    tmp_path: Path, monkeypatch,
) -> None:
    _stub_routing(monkeypatch, {"empty": []})
    case = {
        "id": "empty", "input": {"user_id": "private", "session_id": "empty", "message": "x"},
        "expected": {"selected_agents": ["budget"]},
    }

    metrics = run_dataset(_write_routing_dataset(tmp_path, [case]))

    assert metrics["routing_confusion_totals"] == {"tp": 0, "fp": 0, "fn": 1}
    assert metrics["routing_precision"] == 0
    assert metrics["routing_recall"] == 0
    assert metrics["routing_f1"] == 0


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
