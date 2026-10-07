import csv
import importlib.util
import json
from pathlib import Path

CURRENT_PROMPT_VERSION = json.loads((Path(__file__).resolve().parents[3] / "apps/ai-service/prompts/current/manifest.json").read_text(encoding="utf-8"))["version"]


import pytest

MODULE_PATH = Path(__file__).parents[1] / "representative_user_validation.py"
SPEC = importlib.util.spec_from_file_location("representative_user_validation", MODULE_PATH)
assert SPEC and SPEC.loader
representative_user_validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(representative_user_validation)

REPO_ROOT = Path(__file__).parents[3]
POLICY_PATH = REPO_ROOT / "infra/llmsecops/representative-user-study.json"


def _session(participant_count: int = 5) -> dict:
    return {
        "study_id": "representative-user-explainability",
        "study_version": "v1",
        "conducted_at": "2026-09-01",
        "application_commit_sha": "a" * 40,
        "model_id": "apac.amazon.nova-lite-v1:0",
        "prompt_set_version": CURRENT_PROMPT_VERSION,
        "recruitment": {
            "participants_consented": participant_count,
            "participants_intended_users": participant_count,
            "participants_independent_of_implementation": max(3, participant_count - 1),
            "financial_familiarity_counts": {
                "beginner": 2,
                "intermediate": participant_count - 2,
                "advanced": 0,
            },
            "accessibility_needs_represented": 1,
        },
    }


def _write_session(path: Path, participant_count: int = 5) -> None:
    path.write_text(json.dumps(_session(participant_count)), encoding="utf-8")


def _response_rows(policy: dict, participant_count: int = 5) -> list[dict[str, str]]:
    rows = []
    for participant_number in range(1, participant_count + 1):
        for scenario in policy["scenarios"]:
            source_value = "1" if scenario["source_applicable"] else "na"
            source_likert = "4" if scenario["source_applicable"] else "na"
            rows.append(
                {
                    "participant_id": f"P{participant_number:03d}",
                    "scenario_id": scenario["scenario_id"],
                    "completed": "true",
                    "explanation_correct": "1",
                    "confidence_not_probability_correct": "1",
                    "limitation_correct": "1",
                    "source_use_correct": source_value,
                    "safe_next_action_correct": "1",
                    "would_verify_before_acting": "1",
                    "explanation_clarity_1_to_5": "4",
                    "confidence_clarity_1_to_5": "4",
                    "uncertainty_clarity_1_to_5": "4",
                    "source_clarity_1_to_5": source_likert,
                    "actionability_1_to_5": "4",
                    "issue_codes": "none",
                }
            )
    return rows


def _write_responses(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=representative_user_validation.RESPONSE_FIELDS,
        )
        writer.writeheader()
        writer.writerows(rows)


def test_policy_covers_explanation_confidence_sources_missing_input_and_safety() -> None:
    policy = representative_user_validation.load_policy(POLICY_PATH)

    scenario_ids = {scenario["scenario_id"] for scenario in policy["scenarios"]}

    assert scenario_ids == {
        "budget-explanation",
        "grounded-education",
        "missing-input",
        "regulated-request",
    }
    assert policy["minimum_completed_participants"] == 5
    assert policy["required_model_id"] == "apac.amazon.nova-lite-v1:0"
    assert policy["required_prompt_set_version"] == CURRENT_PROMPT_VERSION
    assert policy["acceptance"]["minimum_binary_rates"]["safe_next_action_correct"] == 1
    assert policy["acceptance"]["maximum_critical_issue_count"] == 0


def test_passing_study_produces_aggregate_evidence_without_participant_ids(
    tmp_path: Path,
) -> None:
    policy = representative_user_validation.load_policy(POLICY_PATH)
    session_path = tmp_path / "session.json"
    responses_path = tmp_path / "responses.csv"
    _write_session(session_path)
    _write_responses(responses_path, _response_rows(policy))

    session = representative_user_validation.load_session(session_path, policy)
    rows = representative_user_validation.load_responses(responses_path, policy)
    report = representative_user_validation.evaluate(policy, session, rows)

    assert report["passed"] is True
    assert report["completed_participant_count"] == 5
    assert report["task_completion_rate"] == 1
    assert report["critical_issue_count"] == 0
    assert "P001" not in json.dumps(report)


def test_safety_misunderstanding_fails_overall_and_scenario_thresholds(
    tmp_path: Path,
) -> None:
    policy = representative_user_validation.load_policy(POLICY_PATH)
    session_path = tmp_path / "session.json"
    responses_path = tmp_path / "responses.csv"
    _write_session(session_path)
    rows = _response_rows(policy)
    affected = next(
        row
        for row in rows
        if row["participant_id"] == "P001"
        and row["scenario_id"] == "regulated-request"
    )
    affected["safe_next_action_correct"] = "0"
    affected["issue_codes"] = "unsafe_next_action"
    _write_responses(responses_path, rows)

    report = representative_user_validation.evaluate(
        policy,
        representative_user_validation.load_session(session_path, policy),
        representative_user_validation.load_responses(responses_path, policy),
    )

    assert report["passed"] is False
    assert report["critical_issue_count"] == 1
    assert any(failure.startswith("BINARY_RATE:safe_next_action_correct") for failure in report["threshold_failures"])
    assert any(failure.startswith("SCENARIO_BINARY_RATE:regulated-request") for failure in report["threshold_failures"])
    assert "CRITICAL_ISSUES:1>0" in report["threshold_failures"]


def test_incomplete_participant_does_not_satisfy_minimum(
    tmp_path: Path,
) -> None:
    policy = representative_user_validation.load_policy(POLICY_PATH)
    session_path = tmp_path / "session.json"
    responses_path = tmp_path / "responses.csv"
    _write_session(session_path)
    rows = _response_rows(policy)
    affected = next(row for row in rows if row["participant_id"] == "P001")
    affected["completed"] = "false"
    for field in (
        *representative_user_validation.BINARY_FIELDS,
        *representative_user_validation.LIKERT_FIELDS,
    ):
        affected[field] = "na"
    _write_responses(responses_path, rows)

    report = representative_user_validation.evaluate(
        policy,
        representative_user_validation.load_session(session_path, policy),
        representative_user_validation.load_responses(responses_path, policy),
    )

    assert report["completed_participant_count"] == 4
    assert any(failure.startswith("MINIMUM_COMPLETED_PARTICIPANTS") for failure in report["threshold_failures"])


def test_response_loader_rejects_identifiers_and_free_text_columns(tmp_path: Path) -> None:
    policy = representative_user_validation.load_policy(POLICY_PATH)
    responses_path = tmp_path / "responses.csv"
    rows = _response_rows(policy)
    rows[0]["participant_id"] = "person@example.com"
    _write_responses(responses_path, rows)

    with pytest.raises(ValueError, match="pseudonymous"):
        representative_user_validation.load_responses(responses_path, policy)

    with responses_path.open("w", newline="", encoding="utf-8") as output:
        fieldnames = [*representative_user_validation.RESPONSE_FIELDS, "comments"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
    with pytest.raises(ValueError, match="free-text or identifying columns"):
        representative_user_validation.load_responses(responses_path, policy)
