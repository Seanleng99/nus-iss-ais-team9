import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import median
from typing import Any

RESPONSE_FIELDS = (
    "participant_id",
    "scenario_id",
    "completed",
    "explanation_correct",
    "confidence_not_probability_correct",
    "limitation_correct",
    "source_use_correct",
    "safe_next_action_correct",
    "would_verify_before_acting",
    "explanation_clarity_1_to_5",
    "confidence_clarity_1_to_5",
    "uncertainty_clarity_1_to_5",
    "source_clarity_1_to_5",
    "actionability_1_to_5",
    "issue_codes",
)
BINARY_FIELDS = (
    "explanation_correct",
    "confidence_not_probability_correct",
    "limitation_correct",
    "source_use_correct",
    "safe_next_action_correct",
    "would_verify_before_acting",
)
LIKERT_FIELDS = (
    "explanation_clarity_1_to_5",
    "confidence_clarity_1_to_5",
    "uncertainty_clarity_1_to_5",
    "source_clarity_1_to_5",
    "actionability_1_to_5",
)
SOURCE_FIELDS = {"source_use_correct", "source_clarity_1_to_5"}
PARTICIPANT_ID_PATTERN = re.compile(r"^P[0-9]{3}$")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_policy(path: Path) -> dict[str, Any]:
    policy = _read_json(path)
    if policy.get("schema_version") != 1:
        raise ValueError("study policy schema_version must be 1")
    scenarios = policy.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("study policy must define scenarios")
    scenario_ids = [item.get("scenario_id") for item in scenarios]
    if any(not value for value in scenario_ids) or len(scenario_ids) != len(
        set(scenario_ids)
    ):
        raise ValueError("study scenario IDs must be non-empty and unique")
    for scenario in scenarios:
        if not isinstance(scenario.get("source_applicable"), bool):
            raise TypeError("each study scenario must define source_applicable")

    acceptance = policy.get("acceptance", {})
    binary_thresholds = acceptance.get("minimum_binary_rates", {})
    likert_thresholds = acceptance.get("minimum_likert_medians", {})
    if set(binary_thresholds) != set(BINARY_FIELDS):
        raise ValueError("study policy must define every binary acceptance threshold")
    if set(likert_thresholds) != set(LIKERT_FIELDS):
        raise ValueError("study policy must define every Likert acceptance threshold")
    if any(not 0 <= float(value) <= 1 for value in binary_thresholds.values()):
        raise ValueError("binary acceptance thresholds must be between 0 and 1")
    if any(not 1 <= float(value) <= 5 for value in likert_thresholds.values()):
        raise ValueError("Likert acceptance thresholds must be between 1 and 5")
    if not 0 <= float(acceptance.get("minimum_task_completion_rate", -1)) <= 1:
        raise ValueError("minimum task completion rate must be between 0 and 1")

    allowed_codes = set(policy.get("allowed_issue_codes", []))
    critical_codes = set(policy.get("critical_issue_codes", []))
    if "none" not in allowed_codes or not critical_codes <= allowed_codes:
        raise ValueError("study policy issue-code controls are invalid")
    if int(policy.get("minimum_completed_participants", 0)) < 1:
        raise ValueError("minimum completed participants must be positive")
    return policy


def _parse_completed(value: str, row_number: int) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"row {row_number}: completed must be true or false")


def _parse_metric(
    value: str,
    *,
    field: str,
    row_number: int,
    completed: bool,
    source_applicable: bool,
) -> int | None:
    normalized = value.strip().lower()
    applicable = source_applicable or field not in SOURCE_FIELDS
    if not completed or not applicable:
        if normalized != "na":
            raise ValueError(f"row {row_number}: {field} must be na when not applicable")
        return None
    if field in BINARY_FIELDS:
        if normalized not in {"0", "1"}:
            raise ValueError(f"row {row_number}: {field} must be 0 or 1")
        return int(normalized)
    try:
        parsed = int(normalized)
    except ValueError as error:
        raise ValueError(f"row {row_number}: {field} must be an integer from 1 to 5") from error
    if not 1 <= parsed <= 5:
        raise ValueError(f"row {row_number}: {field} must be from 1 to 5")
    return parsed


def load_responses(path: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = {item["scenario_id"]: item for item in policy["scenarios"]}
    allowed_codes = set(policy["allowed_issue_codes"])
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != RESPONSE_FIELDS:
            raise ValueError(
                "response CSV header must exactly match the governed template; "
                "free-text or identifying columns are not allowed"
            )
        for row_number, raw in enumerate(reader, start=2):
            participant_id = raw["participant_id"].strip()
            scenario_id = raw["scenario_id"].strip()
            if not PARTICIPANT_ID_PATTERN.fullmatch(participant_id):
                raise ValueError(
                    f"row {row_number}: participant_id must use the pseudonymous P000 format"
                )
            if scenario_id not in scenarios:
                raise ValueError(f"row {row_number}: unknown scenario_id {scenario_id!r}")
            row_key = (participant_id, scenario_id)
            if row_key in seen:
                raise ValueError(f"row {row_number}: duplicate participant/scenario row")
            seen.add(row_key)

            completed = _parse_completed(raw["completed"], row_number)
            metrics = {
                field: _parse_metric(
                    raw[field],
                    field=field,
                    row_number=row_number,
                    completed=completed,
                    source_applicable=scenarios[scenario_id]["source_applicable"],
                )
                for field in (*BINARY_FIELDS, *LIKERT_FIELDS)
            }
            codes = {item.strip() for item in raw["issue_codes"].split(";") if item.strip()}
            if not codes:
                raise ValueError(f"row {row_number}: issue_codes must contain none or a code")
            if unknown := codes - allowed_codes:
                raise ValueError(f"row {row_number}: unknown issue codes {sorted(unknown)}")
            if "none" in codes and len(codes) != 1:
                raise ValueError(f"row {row_number}: none cannot be combined with issue codes")
            rows.append(
                {
                    "participant_id": participant_id,
                    "scenario_id": scenario_id,
                    "completed": completed,
                    "metrics": metrics,
                    "issue_codes": codes,
                }
            )

    if not rows:
        raise ValueError("response CSV contains no participant rows")
    required_scenarios = set(scenarios)
    coverage: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        coverage[row["participant_id"]].add(row["scenario_id"])
    for participant_id, observed in coverage.items():
        if observed != required_scenarios:
            raise ValueError(
                f"{participant_id} must have exactly one row for every governed scenario"
            )
    return rows


def load_session(path: Path, policy: dict[str, Any]) -> dict[str, Any]:
    session = _read_json(path)
    if session.get("study_id") != policy["study_id"]:
        raise ValueError("session study_id does not match the policy")
    if session.get("study_version") != policy["study_version"]:
        raise ValueError("session study_version does not match the policy")
    try:
        date.fromisoformat(session["conducted_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("session conducted_at must be an ISO date") from error
    if not COMMIT_SHA_PATTERN.fullmatch(str(session.get("application_commit_sha", ""))):
        raise ValueError("session application_commit_sha must be a full lowercase commit SHA")
    if session.get("model_id") != policy.get("required_model_id"):
        raise ValueError("session model_id does not match the governed study model")
    if session.get("prompt_set_version") != policy.get("required_prompt_set_version"):
        raise ValueError("session prompt_set_version does not match the governed study prompt set")

    recruitment = session.get("recruitment", {})
    required_counts = (
        "participants_consented",
        "participants_intended_users",
        "participants_independent_of_implementation",
        "accessibility_needs_represented",
    )
    for field in required_counts:
        value = recruitment.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"session recruitment.{field} must be a non-negative integer")
    familiarity = recruitment.get("financial_familiarity_counts", {})
    if set(familiarity) != {"beginner", "intermediate", "advanced"}:
        raise ValueError("session financial familiarity counts are incomplete")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in familiarity.values()):
        raise ValueError("session financial familiarity counts must be non-negative integers")
    if sum(familiarity.values()) != recruitment["participants_consented"]:
        raise ValueError("financial familiarity counts must equal participants_consented")
    if any(
        recruitment[field] > recruitment["participants_consented"]
        for field in required_counts[1:]
    ):
        raise ValueError("recruitment subgroup counts cannot exceed participants_consented")
    return session


def _rate(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _median(values: list[int]) -> float | None:
    return round(float(median(values)), 2) if values else None


def evaluate(
    policy: dict[str, Any],
    session: dict[str, Any],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    participant_ids = {row["participant_id"] for row in rows}
    by_participant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_participant[row["participant_id"]].append(row)
    completed_participants = {
        participant_id
        for participant_id, participant_rows in by_participant.items()
        if all(row["completed"] for row in participant_rows)
    }
    completed_rows = [row for row in rows if row["completed"]]
    completion_rate = round(len(completed_rows) / len(rows), 4)
    issue_counts = Counter(
        code
        for row in rows
        for code in row["issue_codes"]
        if code != "none"
    )

    def metric_values(source_rows: list[dict[str, Any]], field: str) -> list[int]:
        return [
            row["metrics"][field]
            for row in source_rows
            if row["completed"] and row["metrics"][field] is not None
        ]

    binary_rates = {
        field: _rate(metric_values(rows, field)) for field in BINARY_FIELDS
    }
    likert_medians = {
        field: _median(metric_values(rows, field)) for field in LIKERT_FIELDS
    }
    scenario_results: dict[str, Any] = {}
    for scenario in policy["scenarios"]:
        scenario_id = scenario["scenario_id"]
        scenario_rows = [row for row in rows if row["scenario_id"] == scenario_id]
        scenario_results[scenario_id] = {
            "participant_count": len(scenario_rows),
            "completed_count": sum(row["completed"] for row in scenario_rows),
            "completion_rate": round(
                sum(row["completed"] for row in scenario_rows) / len(scenario_rows), 4
            ),
            "binary_rates": {
                field: _rate(metric_values(scenario_rows, field)) for field in BINARY_FIELDS
            },
            "likert_medians": {
                field: _median(metric_values(scenario_rows, field)) for field in LIKERT_FIELDS
            },
            "issue_counts": dict(
                sorted(
                    Counter(
                        code
                        for row in scenario_rows
                        for code in row["issue_codes"]
                        if code != "none"
                    ).items()
                )
            ),
        }

    acceptance = policy["acceptance"]
    failures: list[str] = []
    minimum_completed = int(policy["minimum_completed_participants"])
    if len(completed_participants) < minimum_completed:
        failures.append(
            f"MINIMUM_COMPLETED_PARTICIPANTS:{len(completed_participants)}<{minimum_completed}"
        )
    minimum_completion = float(acceptance["minimum_task_completion_rate"])
    if completion_rate < minimum_completion:
        failures.append(f"TASK_COMPLETION_RATE:{completion_rate}<{minimum_completion}")

    recruitment = session["recruitment"]
    if recruitment["participants_consented"] != len(participant_ids):
        failures.append("PARTICIPANT_COUNT_DOES_NOT_MATCH_SESSION")
    recruitment_policy = policy["recruitment"]
    recruitment_checks = {
        "participants_intended_users": "minimum_intended_users",
        "participants_independent_of_implementation": "minimum_independent_participants",
    }
    for session_field, policy_field in recruitment_checks.items():
        actual = recruitment[session_field]
        required = int(recruitment_policy[policy_field])
        if actual < required:
            failures.append(f"{session_field.upper()}:{actual}<{required}")
    beginner_count = recruitment["financial_familiarity_counts"]["beginner"]
    minimum_beginners = int(recruitment_policy["minimum_beginner_participants"])
    if beginner_count < minimum_beginners:
        failures.append(f"BEGINNER_PARTICIPANTS:{beginner_count}<{minimum_beginners}")

    for field, threshold in acceptance["minimum_binary_rates"].items():
        value = binary_rates[field]
        if value is None or value < float(threshold):
            failures.append(f"BINARY_RATE:{field}:{value}<{threshold}")
    for field, threshold in acceptance["minimum_likert_medians"].items():
        value = likert_medians[field]
        if value is None or value < float(threshold):
            failures.append(f"LIKERT_MEDIAN:{field}:{value}<{threshold}")

    if acceptance.get("apply_thresholds_per_scenario"):
        for scenario_id, result in scenario_results.items():
            if result["completion_rate"] < minimum_completion:
                failures.append(
                    f"SCENARIO_COMPLETION_RATE:{scenario_id}:"
                    f"{result['completion_rate']}<{minimum_completion}"
                )
            for field, threshold in acceptance["minimum_binary_rates"].items():
                value = result["binary_rates"][field]
                if value is not None and value < float(threshold):
                    failures.append(
                        f"SCENARIO_BINARY_RATE:{scenario_id}:{field}:{value}<{threshold}"
                    )
            for field, threshold in acceptance["minimum_likert_medians"].items():
                value = result["likert_medians"][field]
                if value is not None and value < float(threshold):
                    failures.append(
                        f"SCENARIO_LIKERT_MEDIAN:{scenario_id}:{field}:{value}<{threshold}"
                    )

    critical_issue_count = sum(
        issue_counts[code] for code in policy["critical_issue_codes"]
    )
    maximum_critical = int(acceptance["maximum_critical_issue_count"])
    if critical_issue_count > maximum_critical:
        failures.append(f"CRITICAL_ISSUES:{critical_issue_count}>{maximum_critical}")

    return {
        "schema_version": 1,
        "study_id": policy["study_id"],
        "study_version": policy["study_version"],
        "generated_at": datetime.now(UTC).isoformat(),
        "conducted_at": session["conducted_at"],
        "application_commit_sha": session["application_commit_sha"],
        "model_id": session["model_id"],
        "prompt_set_version": session["prompt_set_version"],
        "participant_count": len(participant_ids),
        "completed_participant_count": len(completed_participants),
        "task_count": len(rows),
        "completed_task_count": len(completed_rows),
        "task_completion_rate": completion_rate,
        "recruitment": recruitment,
        "binary_rates": binary_rates,
        "likert_medians": likert_medians,
        "issue_counts": dict(sorted(issue_counts.items())),
        "critical_issue_count": critical_issue_count,
        "scenario_results": scenario_results,
        "threshold_failures": failures,
        "passed": not failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate privacy-safe representative-user validation evidence"
    )
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        policy = load_policy(args.policy)
        session = load_session(args.session, policy)
        rows = load_responses(args.responses, policy)
        report = evaluate(policy, session, rows)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Representative-user validation input is invalid: {error}") from error

    report["policy_sha256"] = _file_sha256(args.policy)
    report["session_sha256"] = _file_sha256(args.session)
    report["responses_sha256"] = _file_sha256(args.responses)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(
            "Representative-user validation failed: "
            + "; ".join(report["threshold_failures"])
        )


if __name__ == "__main__":
    main()
