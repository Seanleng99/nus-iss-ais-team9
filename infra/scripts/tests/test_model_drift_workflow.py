from pathlib import Path

import yaml


def workflow():
    return yaml.load(Path(".github/workflows/model-drift.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_scheduled_drift_is_opt_in_main_only_and_has_a_review_candidate_mode():
    document = workflow()
    assert document["on"]["schedule"][0]["cron"] == "15 2 * * 0"
    assert "pull_request" not in document["on"]
    job = document["jobs"]["monitor"]
    assert "refs/heads/main" in job["if"] and "MODEL_DRIFT_ENABLED" in job["if"]
    assert job["environment"] == "demo"
    assert "baseline_candidate" in document["on"]["workflow_dispatch"]["inputs"]


def test_failed_capture_and_history_restore_cannot_skip_the_report_or_gate():
    steps = workflow()["jobs"]["monitor"]["steps"]
    comparison = next(step for step in steps if step.get("id") == "comparison")
    assert "always()" in comparison["if"]
    assert "--history-required" in comparison["run"]
    state = next(step for step in steps if step.get("with", {}).get("name") == "model-drift-state")
    assert "always()" in state["if"] and state["with"]["retention-days"] == "90"
    gate = steps[-1]
    assert gate["if"] == "always()" and "COMPARISON_OUTCOME" in gate["run"]


def test_secret_keys_do_not_become_arguments_and_review_packet_is_separate():
    steps = workflow()["jobs"]["monitor"]["steps"]
    capture = next(step for step in steps if step.get("id") == "quality")
    assert "--api-key" not in capture["run"]
    assert "MODEL_DRIFT_OPENAI_API_KEY" not in capture["run"]
    review = next(step for step in steps if step.get("name") == "Retain private synthetic calibration packet")
    assert "baseline_candidate == true" in review["if"] and review["with"]["retention-days"] == "7"
    assert any("list-subscriptions-by-topic" in step.get("run", "") for step in steps)
