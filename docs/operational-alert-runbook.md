# Operational Alert Runbook

## Ownership And Response Targets

The Team 9 operations owner is the primary owner of the shared operational-alert mailbox and the CloudWatch dashboard. The owner confirms receipt, classifies the alert, opens the incident record, and coordinates the specialist owner. Access to the mailbox must be limited to current Team 9 operators and reviewed when membership changes.

| Severity | Example signals | Acknowledge target | Primary action owner |
|---|---|---:|---|
| P1 critical | ECS deployment failure, unhealthy backend target, safety-control or authorization failure | 15 minutes during an active demo window | Team 9 operations owner, with security/safety owner engaged immediately |
| P2 high | Backend 5xx threshold, AI generation failure, Bedrock server errors or throttling | 30 minutes during an active demo window | Team 9 operations owner, then backend or AI owner |
| P3 medium | Sustained model latency or AI CPU pressure without errors | 4 business hours | Team 9 operations owner, then AI/cloud owner |

The targets are demo operating objectives, not a staffed 24-hour support commitment. Outside an announced demo window, the owner acknowledges the alert at the start of the next agreed support period. A P1 alert blocks release and continued demonstration until triage establishes a safe path.

## Response Sequence

1. Acknowledge the notification in the team incident record with its UTC time, alarm name, state change, and AWS account/Region. Never copy prompts, financial values, tokens, credentials, or Cognito claims into the record.
2. Open the `ai-financial-wellness-coach-demo-operational` CloudWatch dashboard and verify whether the alarm represents an active condition. Correlate sanitized service events by correlation ID.
3. Classify the incident as security, safety, availability, quality, cost, or false positive. Assign the backend, AI, frontend, cloud, or safety specialist without changing the primary operations owner.
4. For P1, stop promotion immediately. Isolate a compromised service or roll affected ECS services back to their last known-good immutable task definitions when applicable.
5. Preserve privacy-safe evidence: alarm history, deployment event, correlation IDs, image digest, model and prompt versions, corpus versions, and the actions taken.
6. Confirm recovery through service health, the affected alarm returning to `OK`, and the relevant smoke or evaluation gate. Do not infer recovery from an email alone.
7. Record impact, root cause, control effectiveness, owner, follow-up date, and a regression test or monitoring correction before closing the incident.

If the email notification is not received, inspect the SNS subscription state and topic delivery metrics, re-confirm the subscription from the team mailbox, and use the AWS console/dashboard as the temporary observation path. A failed notification test is itself a P2 operational incident.

## Controlled Notification Test

After the AWS confirmation email has been accepted, run:

```powershell
.\infra\scripts\test_operational_alert.ps1 `
  -ExpectedEndpoint <confirmed-team-email> `
  -Confirmation TEST-OPERATIONAL-ALERT
```

The script refuses to run without a confirmed email subscription, refuses to override an alarm that is already genuinely in `ALARM`, verifies that the alarm targets the managed SNS topic, temporarily exercises the CloudWatch alarm action, verifies the successful SNS action in alarm history, restores the original state, and writes a privacy-safe artifact under `artifacts/`. It deliberately cannot assert inbox delivery. A recipient must acknowledge the received test message before governance records describe delivery as verified.

Repeat the controlled test after changing the topic, subscription, alarm action, or operational owner, and at least once before a formally assessed demonstration.
