"""Versioned offline examples that execute the current application components."""

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
from app.rag.ingestion import load_source_manifest
from app.rag.local_documents import DEFAULT_CORPUS_ROOT

DATASET = Path(__file__).resolve().parents[1] / "app/evals/datasets/agent_offline_examples.jsonl"
DATASET_VERSION = "agent-offline-examples-v1"


def _examples(suite: str) -> list[dict]:
    return [
        example
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for example in [json.loads(line)]
        if example["suite"] == suite
    ]


def _run(example: dict):
    provider = example["provider"]
    config_values = {
        "_env_file": None,
        "APP_ENV": "test",
        "MODEL_PROVIDER": "local_fixture",
        "RAG_PROVIDER": "local_fixture",
        "POLICY_RAG_PROVIDER": "local_fixture",
        "AI_SERVICE_API_KEY": "synthetic-local-contract-only",
    }
    if provider == "local_documents":
        manifest = load_source_manifest(DEFAULT_CORPUS_ROOT / "source_manifest.json")
        config_values.update(
            RAG_PROVIDER="local_documents",
            EDUCATION_CORPUS_VERSION=manifest.corpus_version,
        )
    settings = Settings(**config_values)
    orchestrator = AgentOrchestrator(
        config=settings,
        gateway=LocalFixtureModelGateway(),
    )
    return orchestrator.handle(CoachRequest(
        user_id="offline-contract-example",
        session_id=f"offline-contract-{example['id']}",
        message=example["message"],
        snapshot={},
    ))


def _at_path(value: dict, dotted_path: str):
    for part in dotted_path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _assert_example(example: dict, record_property) -> None:
    assert example["dataset_version"] == DATASET_VERSION
    expected = example["expected"]
    record_property("question", example["message"])
    record_property("expected", json.dumps(expected, ensure_ascii=False, sort_keys=True))
    response = _run(example)
    record_property("response", response.answer)

    assert [agent.value for agent in response.selected_agents] == expected["selected_agents"]
    assert response.blocked is expected["blocked"]
    for phrase in expected["answer_contains"]:
        assert phrase.casefold() in response.answer.casefold()

    results = {result.agent.value: result for result in response.agent_results}
    if result_expectation := expected.get("result"):
        result = results[result_expectation["agent"]]
        checks = result_expectation.get("checks", [result_expectation])
        for check in checks:
            actual = _at_path(result.data, check["path"])
            if "length_equals" in check:
                assert len(actual) == check["length_equals"]
            else:
                assert actual == check["equals"]
    if expected_sources := expected.get("source_ids_contains"):
        source_ids = {source.source_id for source in response.sources}
        assert set(expected_sources) <= source_ids
    if expected_urls := expected.get("source_urls_contains"):
        source_urls = {source.canonical_url for source in response.sources}
        assert set(expected_urls) <= source_urls


@pytest.mark.parametrize("example", _examples("orchestrator"), ids=lambda item: item["id"])
def test_example_orchestrator(example: dict, record_property) -> None:
    _assert_example(example, record_property)


@pytest.mark.parametrize("example", _examples("spending"), ids=lambda item: item["id"])
def test_example_spending(example: dict, record_property) -> None:
    _assert_example(example, record_property)


@pytest.mark.parametrize("example", _examples("budget"), ids=lambda item: item["id"])
def test_example_budget(example: dict, record_property) -> None:
    _assert_example(example, record_property)


@pytest.mark.parametrize("example", _examples("goal"), ids=lambda item: item["id"])
def test_example_goal(example: dict, record_property) -> None:
    _assert_example(example, record_property)


@pytest.mark.parametrize("example", _examples("investment"), ids=lambda item: item["id"])
def test_example_investment(example: dict, record_property) -> None:
    _assert_example(example, record_property)


@pytest.mark.parametrize("example", _examples("risk-compliance"), ids=lambda item: item["id"])
def test_example_risk_compliance(example: dict, record_property) -> None:
    _assert_example(example, record_property)


@pytest.mark.parametrize("example", _examples("rag"), ids=lambda item: item["id"])
def test_example_rag(example: dict, record_property) -> None:
    _assert_example(example, record_property)
