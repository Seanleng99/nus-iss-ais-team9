import argparse
import json
from collections import defaultdict
from pathlib import Path

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


def _matches_expected(response, expected: dict) -> bool:
    if "selected_agents" in expected:
        actual = [agent.value for agent in response.selected_agents]
        return actual == expected["selected_agents"]
    if "blocked" in expected:
        return response.blocked == expected["blocked"]
    if "source_ids" in expected:
        data = _agent_data(response, "risk_compliance")
        actual = set(data.get("sources", []))
        return set(expected["source_ids"]).issubset(actual)
    if BUDGET_KEYS.intersection(expected):
        data = _agent_data(response, "budget")
        return all(
            abs(float(data.get(key, -1)) - float(value)) <= 1
            for key, value in expected.items()
        )
    return bool(response.answer)


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
    if "selected_agents" in expected:
        return "routing"
    if "blocked" in expected:
        return "critical_block"
    if "source_ids" in expected:
        return "retrieval"
    if BUDGET_KEYS.intersection(expected):
        return "budget"
    return "general"


def run_dataset(dataset: Path) -> dict[str, float | int]:
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
    )
    total = 0
    passed = 0
    grouped: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    retrieval_recalls: list[float] = []
    with dataset.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            total += 1
            case = json.loads(line)
            if "kind" in case:
                case_passed = _matches_security_case(case)
                category = "security_control"
            else:
                request = CoachRequest(**case["input"])
                response = orchestrator.handle(request)
                case_passed = _matches_expected(response, case["expected"])
                category = _category(case["expected"])
                if category == "retrieval":
                    data = _agent_data(response, "risk_compliance")
                    actual_sources = set(data.get("sources", [])[:3])
                    expected_sources = set(case["expected"]["source_ids"])
                    retrieval_recalls.append(
                        len(actual_sources.intersection(expected_sources)) / len(expected_sources)
                    )
            passed += int(case_passed)
            grouped[category][0] += int(case_passed)
            grouped[category][1] += 1
    accuracy = passed / total if total else 0
    result: dict[str, float | int] = {
        "total": total,
        "passed": passed,
        "accuracy": round(accuracy, 4),
    }
    metric_names = {
        "routing": "routing_accuracy",
        "critical_block": "critical_block_rate",
        "budget": "budget_accuracy",
        "security_control": "security_control_rate",
    }
    for category, metric_name in metric_names.items():
        category_passed, category_total = grouped.get(category, [0, 0])
        if category_total:
            result[metric_name] = round(category_passed / category_total, 4)
    if retrieval_recalls:
        result["source_recall_at_3"] = round(
            sum(retrieval_recalls) / len(retrieval_recalls), 4
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    args = parser.parse_args()
    print(json.dumps(run_dataset(Path(args.dataset)), indent=2))


if __name__ == "__main__":
    main()
