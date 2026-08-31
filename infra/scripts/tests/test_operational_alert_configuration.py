from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALERT_TEST_SCRIPT = PROJECT_ROOT / "infra" / "scripts" / "test_operational_alert.ps1"
OIDC_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "github-actions-oidc.yaml"
APPLICATION_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "demo-application.yaml"
OPERATIONAL_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "aws-operational-validation.yml"
)
RELEASE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "release.yml"


def test_alert_exercise_requires_confirmation_and_uses_full_alarm_path() -> None:
    script = ALERT_TEST_SCRIPT.read_text(encoding="utf-8")

    assert "TEST-OPERATIONAL-ALERT" in script
    assert "list-subscriptions-by-topic" in script
    assert "set-alarm-state" in script
    assert "describe-alarm-history" in script
    assert "Successfully executed action" in script
    assert "human_delivery_acknowledgement" in script
    assert "sns publish" not in script.lower()


def test_operational_workflow_requires_a_confirmed_subscription() -> None:
    template = OIDC_TEMPLATE.read_text(encoding="utf-8")
    workflow = OPERATIONAL_WORKFLOW.read_text(encoding="utf-8")

    assert "OperationalAlertsTopicArn" in template
    assert "sns:ListSubscriptionsByTopic" in template
    assert "OPERATIONAL_ALERTS_TOPIC_ARN" in workflow
    assert "confirmed-email-subscriptions.json" in workflow
    assert "PendingConfirmation" in workflow


def test_operational_workflow_enforces_the_complete_data_lifecycle() -> None:
    workflow = OPERATIONAL_WORKFLOW.read_text(encoding="utf-8")

    assert "app.jobs.purge_data_lifecycle" in workflow
    assert "data-lifecycle-retention-task.json" in workflow
    assert "purge_orchestration_traces" not in workflow


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
