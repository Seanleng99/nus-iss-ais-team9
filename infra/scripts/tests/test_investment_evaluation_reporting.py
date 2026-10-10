"""Reports must describe executed checks and never turn absent evidence into success."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
OWNED_SUITES = tuple(json.loads(
    (ROOT / "infra/llmsecops/agent-test-suites.json").read_text(encoding="utf-8")
)["suites"])


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"infra/scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


junit = load("summarize_pytest_junit")
metrics = load("summarize_investment_evaluations")


@pytest.fixture(autouse=True)
def isolate_ci_summary(monkeypatch):
    """Synthetic reporter examples must never appear as actual CI results."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


def test_every_owned_agent_suite_has_complete_versioned_evaluation_definition():
    ownership = json.loads((ROOT / "infra/llmsecops/agent-test-suites.json").read_text())
    catalog = json.loads(junit.EVALUATION_SPEC.read_text())
    assert set(catalog["suites"]) == set(ownership["suites"])
    for name, definition in catalog["suites"].items():
        assert all(definition[key] for key in (
            "measurement", "datasets", "metrics", "acceptance_criteria", "limitations",
        ))
        assert definition["test_selection"] == ownership["suites"][name]
        paths = {item["path"] for item in definition["datasets"]}
        assert {f"apps/ai-service/{path}" for path in ownership["suites"][name]["test_paths"]} <= paths
        for item in definition["datasets"]:
            assert (ROOT / item["path"]).is_file()
            assert item["expected_outputs"]


@pytest.mark.parametrize("outcomes,accepted,rate", [
    (["passed", "passed"], True, 1),
    (["passed", "failed"], False, .5),
    (["passed", "error"], False, .5),
    (["passed", "skipped"], False, .5),
    ([], False, None),
])
@pytest.mark.parametrize("suite", OWNED_SUITES)
def test_evaluation_acceptance_requires_executed_passing_cases(suite, outcomes, accepted, rate):
    cases = [junit.CaseResult(f"case-{i}", outcome, "", "", "") for i, outcome in enumerate(outcomes)]
    markdown, report = junit.evaluation_summary(suite, cases)
    assert report["accepted"] is accepted
    assert report["results"]["assertion_pass_rate"] == rate
    assert all(len(item["sha256"]) == 64 for item in report["datasets"])
    assert "Expected output" in markdown and "Acceptance criteria" in markdown
    assert "Limitations:" in markdown
    assert sum(report["results"]["outcome_counts"].values()) == len(cases)


def test_expected_case_properties_are_published(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text('<testsuite><testcase name="case"><properties>'
                      '<property name="expected" value="no fabricated source"/>'
                      '</properties></testcase></testsuite>')
    cases = junit.parse_report(report)
    assert cases[0].expected == "no fabricated source"
    assert "Expected output" in junit.render("Integration", cases)
    assert "no fabricated source" in junit.render("Integration", cases)


@pytest.mark.parametrize("suite", [
    "spending-forgotten", "budget-forgotten", "goal-forgotten",
    "investment-forgotten", "risk-compliance-forgotten",
])
def test_unknown_agent_evaluation_definition_is_an_error(suite):
    with pytest.raises(ValueError, match="Missing evaluation"):
        junit.evaluation_summary(suite, [])


def test_missing_owned_definition_fails_reporting_instead_of_omitting_acceptance(tmp_path, monkeypatch):
    catalog = json.loads(junit.EVALUATION_SPEC.read_text())
    del catalog["suites"]["spending-offline"]
    incomplete = tmp_path / "definitions.json"
    incomplete.write_text(json.dumps(catalog))
    monkeypatch.setattr(junit, "EVALUATION_SPEC", incomplete)
    report = tmp_path / "junit.xml"
    report.write_text('<testsuite><testcase name="otherwise-passing"/></testsuite>')
    output = tmp_path / "evaluation.json"
    assert junit.main([
        str(report), "--output", str(tmp_path / "summary.md"), "--title", "Spending",
        "--suite", "spending-offline", "--evaluation-output", str(output),
    ]) == 1
    assert not output.exists()


@pytest.mark.parametrize("group,prefix", [
    ("blocks", "test_blocks_unsafe_request"),
    ("withholds", "test_withholds_unsafe_answer"),
    ("allows", "test_allows_safe_answer"),
])
def test_compliance_reports_record_only_their_selected_scenario_group(group, prefix):
    markdown, report = junit.evaluation_summary(
        f"risk-compliance-functional-{group}", [junit.CaseResult("case", "passed", "", "", "")],
    )
    assert report["test_selection"]["name_prefix"] == prefix
    assert f"-k {prefix}" in markdown


@pytest.mark.parametrize("suite", OWNED_SUITES)
def test_evaluation_json_retains_definition_measurement_and_commit(suite, tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    report = tmp_path / "junit.xml"
    report.write_text('<testsuite><testcase name="synthetic-case"/></testsuite>')
    output = tmp_path / "evaluation.json"
    assert junit.main([
        str(report), "--output", str(tmp_path / "summary.md"), "--title", "Beginner",
        "--suite", suite, "--evaluation-output", str(output),
    ]) == 0
    evidence = json.loads(output.read_text())
    assert evidence["commit_sha"] == "a" * 40
    assert evidence["accepted"] is True
    assert evidence["datasets"] and evidence["acceptance_criteria"] and evidence["metrics"]
    assert evidence["test_selection"]["test_paths"]


def reports():
    evaluation = {"passed": True, "datasets": [{
        "name": "orchestrator", "dataset": "routing.jsonl", "dataset_sha256": "a" * 64,
        "metrics": {"total": 2, "passed": 2, "failed_case_ids": [],
                    "routing_confusion_totals": {"tp": 2, "fp": 0, "fn": 0},
                    "routing_case_diagnostics": [{"id": "route-1", "mode": "automatic",
                        "expected_agents": ["investment_education"], "actual_agents": ["investment_education"],
                        "routing_match": True, "overall_pass": True}]},
        "checks": [{"check": "minimum", "metric": "routing_precision", "actual": 1,
                    "minimum": 1, "passed": True}],
    }]}
    retrieval = {"dataset_sha256": "b" * 64, "corpus_version": "test-v1",
                 "provider": "local_documents", "split": "all", "case_accuracy": 1,
                 "passage_recall_at_3": 1, "scope_accuracy": 1, "by_language": {"en": 1, "zh": 1},
                 "by_status": {"grounded": 1}, "retrieval_gate_passed": True,
                 "cases": 1, "passed_cases": 1,
                 "results": [{"id": "rag-1", "passed": True, "context_words": 200}]}
    return evaluation, retrieval


def test_metrics_summary_shows_actual_thresholds_routing_and_limitations():
    markdown = metrics.render(*reports())
    for text in ("routing_precision", "TP / (TP + FP)", "route-1", "automatic",
                 "passage_recall_at_3", "scope_accuracy", "not measured"):
        assert text in markdown
    assert "1,200" in markdown


@pytest.mark.parametrize("failure", ["missing", "invalid", "failed_gate", "empty_results"])
def test_metrics_report_fails_closed(tmp_path, failure):
    evaluation, retrieval = reports()
    if failure == "failed_gate":
        retrieval["retrieval_gate_passed"] = False
    if failure == "empty_results":
        retrieval["results"] = []
    path = tmp_path / "evaluation.json"
    if failure != "missing":
        path.write_text("invalid" if failure == "invalid" else json.dumps(evaluation))
    rag = tmp_path / "retrieval.json"
    rag.write_text(json.dumps(retrieval))
    assert metrics.main(["--evaluation", str(path), "--retrieval", str(rag),
                         "--output", str(tmp_path / "out.md")]) == 1
    if failure != "failed_gate":
        assert "No passing result is claimed" in (tmp_path / "out.md").read_text()


def test_live_quality_is_not_confused_with_offline_acceptance():
    catalog = json.loads(junit.EVALUATION_SPEC.read_text())
    for definition in catalog["suites"].values():
        assert "offline" in definition["measurement"]
        assert definition["limitations"]
