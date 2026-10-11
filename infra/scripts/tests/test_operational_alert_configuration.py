import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALERT_TEST_SCRIPT = PROJECT_ROOT / "infra" / "scripts" / "test_operational_alert.ps1"
APPLICATION_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "demo-application.yaml"
OPERATIONAL_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "aws-operational-validation.yml"
)
RELEASE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "release.yml"


def operational_jobs():
    return yaml.load(
        OPERATIONAL_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )["jobs"]


def alarm_step():
    return next(
        step for step in operational_jobs()["validate"]["steps"]
        if step.get("name") == "Verify CloudWatch dashboard and alarms"
    )


def test_alert_exercise_requires_confirmation_and_uses_full_alarm_path() -> None:
    script = ALERT_TEST_SCRIPT.read_text(encoding="utf-8")

    assert "TEST-OPERATIONAL-ALERT" in script
    assert "list-subscriptions-by-topic" in script
    assert "set-alarm-state" in script
    assert "describe-alarm-history" in script
    assert "Successfully executed action" in script
    assert "human_delivery_acknowledgement" in script
    assert "sns publish" not in script.lower()


def test_operational_workflow_records_github_only_reporting_without_email_gate() -> None:
    steps = operational_jobs()["validate"]["steps"]
    workflow = "\n".join(step.get("run", "") for step in steps)
    scope = next(
        step for step in steps
        if step.get("name") == "Record GitHub Actions notification scope"
    )
    record = json.loads(scope["run"].split("echo '", 1)[1].split("'", 1)[0])

    assert record == {
        "mode": "github_actions_only",
        "email_delivery_validated": False,
        "cloudwatch_events_forwarded_to_github": False,
    }
    assert "notification-scope.json" in scope["run"]
    assert "GITHUB_STEP_SUMMARY" in scope["run"]
    assert "list-subscriptions-by-topic" not in workflow
    assert "OPERATIONAL_ALERTS_TOPIC_ARN" not in workflow
    assert "sns publish" not in workflow.lower()
    environment = OPERATIONAL_WORKFLOW.read_text(encoding="utf-8")
    assert "OPERATIONAL_ALERTS_TOPIC_ARN:" not in environment


def test_live_result_gate_does_not_mask_an_earlier_infrastructure_failure() -> None:
    gate = next(
        step for step in operational_jobs()["validate"]["steps"]
        if step.get("name") == "Enforce live evaluation and load results"
    )
    assert "always()" in gate["if"]
    assert "steps.live_evaluation.outcome != 'skipped'" in gate["if"]
    assert "steps.load_validation.outcome != 'skipped'" in gate["if"]
    assert "||" in gate["if"]
    assert '"$LIVE_EVALUATION_OUTCOME" != "success"' in gate["run"]
    assert '"$LOAD_VALIDATION_OUTCOME" != "success"' in gate["run"]


def test_operational_profile_allows_complete_multi_agent_requests_without_weakening_success():
    steps = operational_jobs()["validate"]["steps"]
    live = next(step for step in steps if step.get("id") == "live_evaluation")
    load = next(step for step in steps if step.get("id") == "load_validation")
    assert "--timeout-seconds 120" in live["run"]
    assert "--latency-measurement request" in live["run"]
    assert "'90000'" in live["run"]
    assert "'0.25'" in live["run"]
    assert "--timeout-seconds 120" in load["run"]
    assert "'60000'" in load["run"]
    assert load["if"] == "steps.live_evaluation.outcome == 'success'"
    assert "--minimum-pass-rate" not in live["run"]
    assert "--minimum-success-rate" not in load["run"]


def test_operational_workflow_enforces_the_complete_data_lifecycle() -> None:
    jobs = operational_jobs()
    retention = jobs["retention"]
    workflow = "\n".join(step.get("run", "") for step in retention["steps"])

    assert "app.jobs.purge_data_lifecycle" in workflow
    assert "data-lifecycle-retention-task.json" in workflow
    assert "purge_orchestration_traces" not in workflow
    assert not retention.get("needs")
    assert retention["if"] == jobs["validate"]["if"]
    assert "COACH_URL" not in workflow
    assert "SMOKE_BACKEND_API_KEY" not in workflow
    assert "REPEATS" not in workflow
    assert "purge_data_lifecycle" not in json.dumps(jobs["validate"])
    assert retention.get("continue-on-error", "false") == "false"
    upload = next(
        step for step in retention["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "aws-retention-evidence-${{ github.run_id }}"
    assert upload["with"]["retention-days"] == "90"


def test_required_alarm_names_match_the_application_template():
    template = yaml.load(
        APPLICATION_TEMPLATE.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    prefix = "${ProjectName}-demo-"
    defined = {
        resource["Properties"]["AlarmName"].removeprefix(prefix)
        for resource in template["Resources"].values()
        if resource["Type"] == "AWS::CloudWatch::Alarm"
    }
    assert set(json.loads(alarm_step()["env"]["EXPECTED_ALARM_SUFFIXES"])) == defined


@pytest.mark.parametrize("missing, unrelated_count", [
    (None, 0), (None, 6), ("coach-quota-denials", 6), ("backend-5xx", 6),
    ("backend-unhealthy-host", 6), ("ai-generation-failure", 6),
    ("ai-high-cpu", 6), ("all", 6),
])
def test_alarm_gate_requires_each_alarm_even_when_unrelated_alarms_exist(
    tmp_path, missing, unrelated_count,
):
    step = alarm_step()
    suffixes = json.loads(step["env"]["EXPECTED_ALARM_SUFFIXES"])
    prefix = "synthetic-demo-"
    alarms = [
        {"AlarmName": prefix + suffix}
        for suffix in suffixes if suffix != missing and missing != "all"
    ]
    alarms.extend(
        {"AlarmName": prefix + f"unrelated-{index}"} for index in range(unrelated_count)
    )
    evidence = tmp_path / "artifacts"
    evidence.mkdir()
    (evidence / "cloudwatch-alarms.json").write_text(json.dumps({"MetricAlarms": alarms}))
    script = step["run"].split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path,
        env={**os.environ, "ALARM_PREFIX": prefix,
             "EXPECTED_ALARM_SUFFIXES": step["env"]["EXPECTED_ALARM_SUFFIXES"]},
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert (result.returncode == 0) == (missing is None), result.stderr
    if missing is not None:
        assert "Missing required operational alarms:" in result.stderr
        expected_missing = suffixes if missing == "all" else [missing]
        assert all(prefix + suffix in result.stderr for suffix in expected_missing)


def test_deployment_pins_and_release_verifies_lifecycle_configuration() -> None:
    template = APPLICATION_TEMPLATE.read_text(encoding="utf-8")
    release = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    for assignment in (
        "TRACE_RETENTION_DAYS=30",
        "CHAT_RETENTION_DAYS=90",
        "SYNTHETIC_USER_RETENTION_DAYS=30",
        "DURABLE_AGENT_MEMORY_ENABLED=false",
    ):
        assert assignment in release
        assert assignment.partition("=")[0] in template


def test_sns_topic_policy_allows_only_scoped_alarm_and_event_publishers() -> None:
    template = APPLICATION_TEMPLATE.read_text(encoding="utf-8")

    assert "Service: cloudwatch.amazonaws.com" in template
    assert "Service: events.amazonaws.com" in template
    assert template.count("AWS:SourceAccount: !Ref AWS::AccountId") == 2
    assert "alarm:${ProjectName}-demo-*" in template
    assert "AWS:SourceArn: !GetAtt EcsDeploymentFailureRule.Arn" in template
