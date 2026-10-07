"""Frozen reasoning cases run through the real orchestrator, without agent overrides.

This module is an evaluation client only. Runtime routing never imports its expectations.
"""

import argparse
import copy
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from app.core.config import Settings
from app.core.guardrails import redact_sensitive_text
from app.core.schemas import CoachRequest
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator


def graph_evidence(response):
    events = response.audit.get("events", [])
    owners = {event["task_id"]: event["details"]["agent"] for event in events
              if event["event_type"] == "task.created"}
    owners.update({event["task_id"]: event["actor"] for event in events
                   if event["event_type"] == "task.started"})
    edges = sorted({(owners.get(edge["requester_task_id"], "unknown"),
                     owners.get(edge["provider_task_id"], "tool"), edge["capability"])
                    for edge in response.audit.get("dependency_edges", [])})
    intervals, started = [], {}
    for event in events:
        key = event.get("task_id")
        if event["event_type"] == "task.started":
            started[key] = datetime.fromisoformat(event["occurred_at"])
        elif event["event_type"] == "task.execution.finished" and key in started:
            intervals.append((owners.get(key, event["actor"]), started.pop(key),
                              datetime.fromisoformat(event["occurred_at"])))
    overlaps = sorted({tuple(sorted((a[0], b[0]))) for i, a in enumerate(intervals)
                       for b in intervals[i + 1:] if a[0] != b[0]
                       and max(a[1], b[1]) < min(a[2], b[2])})
    initial = next((event["details"].get("after", {}).get("selected_agents", [])
                    for event in events if event["event_type"] == "routing.completed"), [])
    return {"initial_agents": initial, "final_agents": sorted(a.value for a in response.selected_agents),
            "edges": [list(edge) for edge in edges], "overlaps": [list(pair) for pair in overlaps],
            "answer_status": response.audit.get("answer_status"), "blocked": response.blocked,
            "follow_up": response.audit.get("follow_up", {}),
            "review_rounds": sum(e["event_type"] == "compliance.completed" for e in events),
            "trace_id": response.audit.get("trace_id")}


def _at_path(value, path):
    for key in path.split("."):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def assess(response, expected):
    evidence = graph_evidence(response)
    failures = []
    variants = expected.get("agent_sets", [])
    if variants and evidence["final_agents"] not in [sorted(v) for v in variants]:
        failures.append("AGENT_SET")
    actual_edges = {tuple(e) for e in evidence["edges"]}
    for edge in expected.get("required_edges", []):
        if tuple(edge) not in actual_edges:
            failures.append("MISSING_EDGE:" + "/".join(edge))
    if expected.get("no_specialist_edges") and any(e[1] != "tool" for e in actual_edges):
        failures.append("UNEXPECTED_SPECIALIST_EDGE")
    for edge in expected.get("forbidden_edges", []):
        if tuple(edge) in actual_edges:
            failures.append("FORBIDDEN_EDGE:" + "/".join(edge))
    if evidence["answer_status"] not in expected.get("answer_statuses", ["answered"]):
        failures.append("ANSWER_STATUS")
    if evidence["blocked"]:
        failures.append("WITHHELD")
    if evidence["review_rounds"] == 0:
        failures.append("NO_INDEPENDENT_REVIEW")
    if "follow_up_status" in expected and evidence["follow_up"].get("status") != expected["follow_up_status"]:
        failures.append("FOLLOW_UP")
    for pair in expected.get("parallel_pairs", []):
        if sorted(pair) not in evidence["overlaps"]:
            failures.append("NO_OBSERVED_OVERLAP:" + "/".join(pair))
    data = {result.agent.value: result.data for result in response.agent_results}
    facts = []
    for item in expected.get("facts", []):
        try:
            actual = _at_path(data[item["agent"]], item["path"])
            matches = actual == item["value"] and not (
                isinstance(actual, bool) and type(item["value"]) in {int, float}
            )
        except (KeyError, IndexError, TypeError, ValueError):
            actual, matches = None, False
        facts.append({**item, "actual": actual, "passed": matches})
        if not matches:
            failures.append("FACT:" + item["agent"] + "/" + item["path"])
    evidence["facts"] = facts
    # Graph/numeric checks do not establish semantic completeness or presentation.
    evidence["content_review"] = "required"
    return {"checks_passed": not failures, "failures": failures, "evidence": evidence}


def load_suite(path):
    suite = json.loads(path.read_text(encoding="utf-8"))
    if suite.get("schema_version") != 1 or not suite.get("cases"):
        raise ValueError("A versioned nonempty reasoning suite is required")
    seen = set()
    for case in suite["cases"]:
        if case["id"] in seen or case.get("previous_case") not in (None, *seen):
            raise ValueError("Case IDs must be unique and follow-ups must reference earlier cases")
        seen.add(case["id"])
        if "requested_agents" in case.get("input", {}) or "requested_agents" in suite["profile"]:
            raise ValueError("Reasoning acceptance forbids specialist overrides")
        if not case.get("expected") or not case.get("content_checks"):
            raise ValueError("Graph expectations and human content checks must both be frozen")
        CoachRequest(user_id="evaluation", session_id="validation",
                     **{**suite["profile"], **case["input"]})
    return suite


def _follow_up_input(previous):
    request, response = previous
    available = not response.blocked and response.audit.get("answer_status") == "answered"
    referents = response.audit.get("turn_decision", {}).get("referents", []) if available else []
    return {"conversation_context": [
        {"role": "user", "content": request.message},
        {"role": "assistant", "content": response.answer[:1500],
         "answer_status": "available" if available else "withheld"}],
        "session_context": {"referents": referents}}


def run_suite(path, *, config, repeats=3, build_commit="unknown", orchestrator=None):
    if not 1 <= repeats <= 5:
        raise ValueError("Repeats must be between 1 and 5")
    suite = load_suite(path)
    coach = orchestrator or AgentOrchestrator(config=config)
    rows = []
    for repeat in range(1, repeats + 1):
        history = {}
        for case in suite["cases"]:
            row = {"case_id": case["id"], "repeat": repeat, "content_checks": case["content_checks"]}
            start = perf_counter()
            try:
                values = {**copy.deepcopy(suite["profile"]), **copy.deepcopy(case["input"])}
                if case.get("previous_case"):
                    if case["previous_case"] not in history:
                        raise ModelGatewayError("Preceding evaluation turn was unavailable.", code="PREVIOUS_CASE_UNAVAILABLE")
                    values.update(_follow_up_input(history[case["previous_case"]]))
                request = CoachRequest(user_id="reasoning-evaluation", session_id=f"case-{repeat}-{case['id']}", **values)
                response = coach.handle(request)
                history[case["id"]] = (request, response)
                row.update(assess(response, case["expected"]))
                row["answer_for_review"] = redact_sensitive_text(response.answer)[0]
                row["sources"] = [source.model_dump(mode="json") for source in response.sources]
            except Exception as exc:  # noqa: BLE001 - safe failure collection is the evaluation contract
                # Persist a safe failure code and continue collecting the matrix.
                code = exc.code if isinstance(exc, ModelGatewayError) else type(exc).__name__.upper()
                row.update(checks_passed=False, failures=[code], evidence={"content_review": "required"})
            row["duration_ms"] = round((perf_counter() - start) * 1000, 2)
            rows.append(row)
    return {"suite_id": suite["suite_id"], "suite_sha256": sha256(path.read_bytes()).hexdigest(),
            "measurement": "offline_fixture_contract" if config.model_provider == "local_fixture" else "in_process_production_model",
            "build_commit": build_commit, "executed_at": datetime.now(UTC).isoformat(),
            "provider": config.model_provider, "model_id": config.model_id,
            "model_role_overrides": {role: config.model_policy(role, config.model_max_tokens).model_dump()
                                     for role in config.model_role_overrides},
            "temperatures": {"router": config.router_temperature, "agent": config.agent_temperature,
                             "compliance": config.compliance_temperature},
            "retrievers": {"education": type(coach.education_retriever).__name__,
                           "policy": type(coach.policy_retriever).__name__},
            "prompt_version": config.prompt_set_version,
            "workflow_timeout_seconds": config.workflow_timeout_seconds,
            "repeats": repeats, "checked": len(rows), "checks_passed": sum(row["checks_passed"] for row in rows),
            "acceptance": "pending_content_review",
            "limitations": ["Passing fixture checks do not measure semantic routing accuracy.",
                            "In-process model calls do not verify deployed browser/backend transport limits.",
                            "A human must assess each recorded answer against its frozen content checks."],
            "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--provider", choices=["local_fixture", "openai"], required=True)
    parser.add_argument("--model-id")
    parser.add_argument("--build-commit", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    options = {"MODEL_PROVIDER": args.provider, "REVIEW_DIAGNOSTICS_DIR": None}
    if args.model_id:
        options["MODEL_ID"] = args.model_id
    result = run_suite(args.suite, config=Settings(**options), repeats=args.repeats, build_commit=args.build_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("measurement", "checked", "checks_passed", "acceptance")}))
    raise SystemExit(0 if result["checks_passed"] == result["checked"] else 1)


if __name__ == "__main__":
    main()
