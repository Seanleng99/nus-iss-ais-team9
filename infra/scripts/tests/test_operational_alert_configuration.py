from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALERT_TEST_SCRIPT = PROJECT_ROOT / "infra" / "scripts" / "test_operational_alert.ps1"
OIDC_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "github-actions-oidc.yaml"
APPLICATION_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "demo-application.yaml"
OPERATIONAL_WORKFLOW = (
    PROJECT_ROOT / ".github" / "workflows" / "aws-operational-validation.yml"
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


def test_operational_workflow_requires_a_confirmed_subscription() -> None:
    template = OIDC_TEMPLATE.read_text(encoding="utf-8")
    workflow = OPERATIONAL_WORKFLOW.read_text(encoding="utf-8")

    assert "OperationalAlertsTopicArn" in template
    assert "sns:ListSubscriptionsByTopic" in template
    assert "OPERATIONAL_ALERTS_TOPIC_ARN" in workflow
    assert "confirmed-email-subscriptions.json" in workflow
    assert "PendingConfirmation" in workflow


def test_sns_topic_policy_allows_only_scoped_alarm_and_event_publishers() -> None:
    template = APPLICATION_TEMPLATE.read_text(encoding="utf-8")

    assert "Service: cloudwatch.amazonaws.com" in template
    assert "Service: events.amazonaws.com" in template
    assert template.count("AWS:SourceAccount: !Ref AWS::AccountId") == 2
    assert "alarm:${ProjectName}-demo-*" in template
    assert "AWS:SourceArn: !GetAtt EcsDeploymentFailureRule.Arn" in template
