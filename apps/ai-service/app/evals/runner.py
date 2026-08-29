import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.guardrails import inspect_prompt, sanitize_rag_document, validate_tool_permission
from app.core.schemas import AgentName, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator

BUDGET_KEYS = {"disposable_income", "needs", "wants", "savings"}


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
            and "approved knowledge base does not contain enough information" in response.answer
        )
    if "policy_finding_prefixes" in expected:
        findings = _policy_findings(response)
        checks.extend(
            any(finding.startswith(prefix) for finding in findings)
            for prefix in expected["policy_finding_prefixes"]
        )
    if "minimum_disclaimers" in expected:
        checks.append(len(response.disclaimers) >= int(expected["minimum_disclaimers"]))
    if BUDGET_KEYS.intersection(expected):
        data = _agent_data(response, "budget")
        checks.append(
            all(
                abs(float(data.get(key, -1)) - float(value)) <= 1
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
    inputs = case.get("inputs", [])
    compare = case.get("compare", [])
    if len(inputs) != 2 or not compare:
        raise ValueError("Fairness cases require exactly two inputs and comparison fields")
    responses = [orchestrator.handle(CoachRequest(**item)) for item in inputs]
    return all(
        _fairness_projection(responses[0], field)
        == _fairness_projection(responses[1], field)
        for field in compare
    )


def _matches_security_case(case: dict) -> bool:
    kind = case["kind"]
    case_input = case["input"]
    expected = case["expected"]

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
    with dataset.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            case = json.loads(line)
            if case.get("kind") == "fairness_pair":
                case_passed = _matches_fairness_case(orchestrator, case)
                category = "fairness_consistency"
            elif "kind" in case:
                case_passed = _matches_security_case(case)
                category = "security_control"
            else:
                request = CoachRequest(**case["input"])
                response = orchestrator.handle(request)
                case_passed = _matches_expected(response, case["expected"])
                category = _category(case["expected"])
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
        "total": total,
        "passed": passed,
        "accuracy": round(accuracy, 4),
        "failed_case_ids": failed_case_ids,
    }
    metric_names = {
        "routing": "routing_accuracy",
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
