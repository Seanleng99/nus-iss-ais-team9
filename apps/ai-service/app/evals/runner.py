import argparse
import json
import re
from collections import defaultdict
from math import isfinite
from pathlib import Path
from typing import Any

from coach_i18n import load_data, translate

from app.core.citations import render_citations
from app.core.config import Settings
from app.core.guardrails import inspect_prompt, sanitize_rag_document, validate_tool_permission
from app.core.schemas import AgentName, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator

BUDGET_KEYS = {"disposable_income", "needs", "wants", "savings"}
FAIRNESS_EXPECTED_FIELDS = BUDGET_KEYS | {
    "blocked", "selected_agents", "forbidden_agents", "dependency_capabilities", "needs_input_agents",
    "source_ids", "policy_source_ids", "evidence_gap", "response_language", "answer_language",
    "evidence_status", "unanswered_topics", "response_excludes", "policy_finding_prefixes",
    "minimum_disclaimers", "agent_data",
}


def _agent_data(response, agent_name: str) -> dict:
    for result in response.agent_results:
        if result.agent.value == agent_name:
            return result.data
    return {}


def _dependency_capabilities(response) -> set[str]:
    return {
        item["capability"]
        for item in response.audit.get("dependency_resolutions", [])
        if item["resolution"] in {"scheduled", "resolved", "reused"}
    }


def _needs_input_agents(response) -> set[str]:
    return {
        result.agent.value
        for result in response.agent_results
        if result.data.get("needs_input") is True
    }


def _policy_findings(response) -> list[str]:
    return [
        finding
        for result in response.agent_results
        for finding in result.policy_notes
    ]


def _policy_source_ids(response) -> set[str]:
    return {
        str(source["source_id"])
        for source in response.audit.get("policy_sources", [])
    }


def _matches_budget_amount(actual: Any, expected: Any) -> bool:
    if expected is None:
        return actual is None
    if actual is None or isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        actual_amount = float(actual)
        expected_amount = float(expected)
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        isfinite(actual_amount)
        and isfinite(expected_amount)
        and abs(actual_amount - expected_amount) <= 1
    )


def _matches_expected(response, expected: dict) -> bool:
    checks: list[bool] = []
    if "dependency_capabilities" in expected:
        checks.append(
            set(expected["dependency_capabilities"])
            == _dependency_capabilities(response)
        )
    if "needs_input_agents" in expected:
        checks.append(set(expected["needs_input_agents"]) == _needs_input_agents(response))
    if "selected_agents" in expected:
        actual = [agent.value for agent in response.selected_agents]
        checks.append(actual == expected["selected_agents"])
    if "forbidden_agents" in expected:
        actual = {agent.value for agent in response.selected_agents}
        checks.append(actual.isdisjoint(expected["forbidden_agents"]))
    if "blocked" in expected:
        checks.append(response.blocked == expected["blocked"])
    if "source_ids" in expected:
        actual = {source.source_id for source in response.sources}
        checks.append(set(expected["source_ids"]).issubset(actual))
    if "policy_source_ids" in expected:
        checks.append(
            set(expected["policy_source_ids"]).issubset(_policy_source_ids(response))
        )
    if expected.get("evidence_gap"):
        data = _agent_data(response, "investment_education")
        checks.append(
            data.get("evidence_status") == "insufficient"
            and translate("education.insufficient_evidence", response.audit.get("response_locale")) in response.answer
        )
    if "response_language" in expected:
        data = _agent_data(response, "investment_education")
        checks.append(data.get("response_language") == expected["response_language"])
    if expected.get("answer_language") == "Chinese":
        prose = response.answer
        for source in response.sources:
            prose = prose.replace(render_citations(
                f"[source:{source.source_id}]", [source], response.audit.get("response_locale")
            ), "")
        letters = re.findall(load_data("scripts")["education_prose_letters"], prose)
        chinese = re.findall(load_data("scripts")["han_basic"], prose)
        checks.append(len(chinese) >= 10 and len(chinese) / max(1, len(letters)) >= 0.4)
    if "evidence_status" in expected:
        checks.append(_agent_data(response, "investment_education").get("evidence_status") == expected["evidence_status"])
    if "unanswered_topics" in expected:
        checks.append(set(expected["unanswered_topics"]) == set(_agent_data(response, "investment_education").get("unanswered_topics", [])))
    for text in expected.get("response_excludes", []):
        checks.append(text not in response.model_dump_json())
    if response.blocked:
        checks.append(all(result.blocked for result in response.agent_results))
        checks.append(not response.sources)
    if "policy_finding_prefixes" in expected:
        findings = _policy_findings(response)
        checks.extend(
            any(finding.startswith(prefix) for finding in findings)
            for prefix in expected["policy_finding_prefixes"]
        )
    if "minimum_disclaimers" in expected:
        checks.append(len(response.disclaimers) >= int(expected["minimum_disclaimers"]))
    for agent, fields in expected.get("agent_data", {}).items():
        data = _agent_data(response, agent)
        checks.append(all(key in data and data[key] == value for key, value in fields.items()))
    if BUDGET_KEYS.intersection(expected):
        data = _agent_data(response, "budget")
        checks.append(
            all(
                key in data and _matches_budget_amount(data[key], value)
                for key, value in expected.items()
                if key in BUDGET_KEYS
            )
        )
    return all(checks) if checks else bool(response.answer)


def _fairness_projection(response, field: str):
    if field == "selected_agents":
        return [agent.value for agent in response.selected_agents]
    if field == "blocked":
        return response.blocked
    if field == "dependency_capabilities":
        return sorted(_dependency_capabilities(response))
    if field == "needs_input_agents":
        return sorted(_needs_input_agents(response))
    if field == "source_ids":
        return sorted(source.source_id for source in response.sources)
    if field == "budget_data":
        data = _agent_data(response, "budget")
        return {key: data.get(key) for key in sorted(BUDGET_KEYS)}
    if field == "goal_data":
        data = _agent_data(response, "goal_strategy")
        return {
            "projections": data.get("projections", []),
            "feasibility": data.get("feasibility", []),
        }
    if field == "evidence_status":
        return _agent_data(response, "investment_education").get("evidence_status")
    raise ValueError(f"Unsupported fairness comparison field: {field}")


def _matches_fairness_case(orchestrator: AgentOrchestrator, case: dict) -> bool:
    passed, _ = _fairness_case_outputs(orchestrator, case)
    return passed


def validate_fairness_expectations(case: dict) -> None:
    expected = case.get("expected")
    if (not isinstance(expected, dict) or type(expected.get("blocked")) is not bool
            or len(expected) < 2 or not set(expected) <= FAIRNESS_EXPECTED_FIELDS):
        raise ValueError("Fairness cases require independent expected outcomes, including blocked; unknown assertions are invalid")
    side_expected = case.get("side_expected", [{}, {}])
    if (not isinstance(side_expected, list) or len(side_expected) != 2
            or any(not isinstance(item, dict) or not set(item) <= FAIRNESS_EXPECTED_FIELDS
                   or set(item) & set(expected) for item in side_expected)):
        raise ValueError("Fairness side expectations require two objects without overriding common outcomes")


def _fairness_case_outputs(orchestrator: AgentOrchestrator, case: dict) -> tuple[bool, list[dict]]:
    inputs = case.get("inputs", [])
    compare = case.get("compare", [])
    if len(inputs) != 2 or not compare:
        raise ValueError("Fairness cases require exactly two inputs and comparison fields")
    validate_fairness_expectations(case)
    expected = case["expected"]
    side_expected = case.get("side_expected", [{}, {}])
    responses = [orchestrator.handle(CoachRequest(**item)) for item in inputs]
    outputs = [
        {
            "side": "A" if index == 0 else "B",
            "question": item["message"],
            "actual_answer": response.answer,
            "independent_correctness_passed": _matches_expected(response, {**expected, **side_expected[index]}),
            "actual_output": {
                field: _fairness_projection(response, field)
                for field in compare
            },
        }
        for index, (item, response) in enumerate(zip(inputs, responses))
    ]
    return (
        all(item["independent_correctness_passed"] for item in outputs)
        and outputs[0]["actual_output"] == outputs[1]["actual_output"],
        outputs,
    )


def _security_case_actual(case: dict) -> dict[str, Any]:
    kind = case["kind"]
    case_input = case["input"]

    if kind == "user_prompt":
        decision = inspect_prompt(case_input["text"])
        actual = {
            "allowed": decision.allowed,
            "sanitized_text": decision.sanitized_text,
            "findings": decision.findings,
        }
    elif kind == "rag_document":
        decision = sanitize_rag_document(case_input["text"])
        actual = {
            "allowed": decision.allowed,
            "sanitized_text": decision.sanitized_text,
            "findings": decision.findings,
        }
    elif kind == "tool_permission":
        denied = False
        try:
            validate_tool_permission(AgentName(case_input["agent"]), case_input["tool"])
        except PermissionError:
            denied = True
        actual = {"denied": denied}
    else:
        raise ValueError(f"Unsupported security evaluation kind: {kind}")

    return actual


def _matches_security_case(case: dict) -> bool:
    actual = _security_case_actual(case)
    expected = case["expected"]
    if any(actual.get(key) != value for key, value in expected.items() if key in actual):
        return False
    if (
        "sanitized_contains" in expected
        and expected["sanitized_contains"] not in actual.get("sanitized_text", "")
    ):
        return False
    return "finding_prefix" not in expected or any(
        finding.startswith(expected["finding_prefix"])
        for finding in actual.get("findings", [])
    )


def _actual_conversation_output(response, expected: dict) -> dict[str, Any]:
    output: dict[str, Any] = {
        "answer": response.answer,
        "selected_agents": [agent.value for agent in response.selected_agents],
        "blocked": response.blocked,
        "source_ids": sorted(source.source_id for source in response.sources),
        "policy_source_ids": sorted(_policy_source_ids(response)),
        "policy_findings": _policy_findings(response),
        "dependency_capabilities": sorted(_dependency_capabilities(response)),
        "needs_input_agents": sorted(_needs_input_agents(response)),
        "disclaimers": response.disclaimers,
    }
    if BUDGET_KEYS.intersection(expected):
        budget = _agent_data(response, "budget")
        output["budget_values"] = {key: budget.get(key) for key in sorted(BUDGET_KEYS)}
    if any(key in expected for key in ("evidence_status", "evidence_gap", "response_language", "unanswered_topics")):
        education = _agent_data(response, "investment_education")
        output["education"] = {
            key: education.get(key)
            for key in ("evidence_status", "response_language", "unanswered_topics")
            if key in education
        }
    return output


def _category(expected: dict) -> str:
    if "dependency_capabilities" in expected or "needs_input_agents" in expected:
        return "dependency"
    if "selected_agents" in expected:
        return "routing"
    if "policy_source_ids" in expected:
        return "policy_retrieval"
    if "source_ids" in expected:
        return "retrieval"
    if "evidence_gap" in expected:
        return "evidence_gap"
    if BUDGET_KEYS.intersection(expected):
        return "budget"
    if expected.get("blocked") is True:
        return "critical_block"
    return "general"


def run_dataset(dataset: Path) -> dict[str, Any]:
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
    )
    total = 0
    passed = 0
    failed_case_ids: list[str] = []
    grouped: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    retrieval_recalls: list[float] = []
    policy_retrieval_recalls: list[float] = []
    routing_case_diagnostics: list[dict[str, Any]] = []
    case_diagnostics: list[dict[str, Any]] = []
    routing_counts = {"tp": 0, "fp": 0, "fn": 0}
    routing_matches: dict[str, list[int]] = {
        "automatic": [0, 0],
        "explicit_override": [0, 0],
    }
    with dataset.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            case = json.loads(line)
            if case.get("kind") == "fairness_pair":
                case_passed, paired_outputs = _fairness_case_outputs(orchestrator, case)
                category = "fairness_consistency"
                case_diagnostics.append({
                    "id": str(case.get("id", "unknown")),
                    "case_type": "fairness_pair",
                    "question": "N/A",
                    "paired_inputs": [
                        {"side": item["side"], "question": item["question"]}
                        for item in paired_outputs
                    ],
                    "expected_output": {
                        "comparison_fields": case["compare"],
                        "automated_expectations": case["expected"],
                        "requirement": "Both answers must independently meet expectations and their compared outputs must match.",
                    },
                    "actual_answer": "N/A",
                    "actual_output": paired_outputs,
                    "passed": case_passed,
                })
            elif "kind" in case:
                actual_output = _security_case_actual(case)
                case_passed = _matches_security_case(case)
                category = "security_control"
                case_diagnostics.append({
                    "id": str(case.get("id", "unknown")),
                    "case_type": "security_control",
                    "question": case["input"].get("text", "N/A"),
                    "test_input": case["input"],
                    "expected_output": case["expected"],
                    "actual_answer": "N/A",
                    "actual_output": actual_output,
                    "passed": case_passed,
                })
            else:
                request = CoachRequest(**case["input"])
                response = orchestrator.handle(request)
                case_passed = _matches_expected(response, case["expected"])
                category = _category(case["expected"])
                expected_output = case.get("expected", {})
                if "answer_rubric" in case or "forbidden_behaviors" in case:
                    expected_output = {
                        "automated_expectations": expected_output,
                        "human_review_criteria": {
                            key: case[key]
                            for key in ("answer_rubric", "forbidden_behaviors")
                            if key in case
                        },
                    }
                case_diagnostics.append({
                    "id": str(case.get("id", "unknown")),
                    "case_type": "conversation",
                    "question": request.message,
                    "expected_output": expected_output,
                    "actual_answer": response.answer,
                    "actual_output": _actual_conversation_output(response, case["expected"]),
                    "passed": case_passed,
                })
                if "selected_agents" in case["expected"]:
                    expected_agents = set(case["expected"]["selected_agents"])
                    actual_agents = {agent.value for agent in response.selected_agents}
                    routing_match = actual_agents == expected_agents
                    mode = "explicit_override" if request.requested_agents else "automatic"
                    route_counts = routing_matches[mode]
                    route_counts[0] += int(routing_match)
                    route_counts[1] += 1
                    routing_counts["tp"] += len(expected_agents & actual_agents)
                    routing_counts["fp"] += len(actual_agents - expected_agents)
                    routing_counts["fn"] += len(expected_agents - actual_agents)
                    routing_case_diagnostics.append({
                        "id": str(case.get("id", "unknown")),
                        "mode": mode,
                        "expected_agents": sorted(expected_agents),
                        "actual_agents": sorted(actual_agents),
                        "routing_match": routing_match,
                        "overall_pass": case_passed,
                        "question": request.message,
                        "expected_output": case["expected"],
                        "actual_answer": response.answer,
                    })
                if category == "retrieval":
                    actual_sources = {
                        source.source_id for source in response.sources[:3]
                    }
                    expected_sources = set(case["expected"]["source_ids"])
                    retrieval_recalls.append(
                        len(actual_sources.intersection(expected_sources)) / len(expected_sources)
                    )
                elif category == "policy_retrieval":
                    actual_sources = list(_policy_source_ids(response))[:3]
                    expected_sources = set(case["expected"]["policy_source_ids"])
                    policy_retrieval_recalls.append(
                        len(set(actual_sources).intersection(expected_sources))
                        / len(expected_sources)
                    )
            passed += int(case_passed)
            if not case_passed:
                failed_case_ids.append(str(case.get("id", "unknown")))
            grouped[category][0] += int(case_passed)
            grouped[category][1] += 1
    accuracy = passed / total if total else 0
    result: dict[str, Any] = {
        "measurement": "offline_fixture_contract",
        "total": total,
        "passed": passed,
        "accuracy": round(accuracy, 4),
        "failed_case_ids": failed_case_ids,
        "case_diagnostics": case_diagnostics,
    }
    metric_names = {
        "critical_block": "critical_block_rate",
        "budget": "budget_accuracy",
        "security_control": "security_control_rate",
        "evidence_gap": "evidence_gap_rate",
        "dependency": "dependency_accuracy",
        "fairness_consistency": "fairness_consistency_rate",
    }
    for category, metric_name in metric_names.items():
        category_passed, category_total = grouped.get(category, [0, 0])
        if category_total:
            result[metric_name] = round(category_passed / category_total, 4)
    if routing_case_diagnostics:
        tp, fp, fn = (routing_counts[key] for key in ("tp", "fp", "fn"))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        automatic_matches, automatic_total = routing_matches["automatic"]
        override_matches, override_total = routing_matches["explicit_override"]
        result.update({
            "routing_case_count": len(routing_case_diagnostics),
            "routing_accuracy": round(
                sum(item["routing_match"] for item in routing_case_diagnostics)
                / len(routing_case_diagnostics),
                4,
            ),
            "routing_precision": round(precision, 4),
            "routing_recall": round(recall, 4),
            "routing_f1": round(f1, 4),
            "routing_confusion_totals": routing_counts,
            "automatic_routing_case_count": automatic_total,
            "explicit_override_case_count": override_total,
            "routing_case_diagnostics": routing_case_diagnostics,
        })
        if automatic_total:
            result["automatic_routing_accuracy"] = round(
                automatic_matches / automatic_total, 4
            )
        if override_total:
            result["override_accuracy"] = round(override_matches / override_total, 4)
    if retrieval_recalls:
        result["source_recall_at_3"] = round(
            sum(retrieval_recalls) / len(retrieval_recalls), 4
        )
    if policy_retrieval_recalls:
        result["policy_source_recall_at_3"] = round(
            sum(policy_retrieval_recalls) / len(policy_retrieval_recalls), 4
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    print(json.dumps(run_dataset(Path(args.dataset)), indent=2))


if __name__ == "__main__":
    main()
