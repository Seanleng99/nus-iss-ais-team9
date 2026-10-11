# Operational Alert Runbook

## Ownership And Response Targets

The Team 9 operations owner reviews AWS Operational Validation and Model Drift Monitoring failures in GitHub Actions, retained evidence, and the CloudWatch dashboard. Both workflows currently use GitHub Actions reporting; operational validation records this scope in `notification-scope.json` and does not require an email subscription. GitHub reporting covers workflow outcomes and does not forward CloudWatch alarm events. The owner classifies the alert, opens the incident record, and coordinates the specialist owner. If email alerts are restored, the owner also manages the shared operational-alert mailbox and confirms receipt; mailbox access must be limited to current Team 9 operators and reviewed when membership changes.

| Severity | Example signals | Acknowledge target | Primary action owner |
|---|---|---:|---|
| P1 critical | ECS deployment failure, unhealthy backend target, safety-control or authorization failure | 15 minutes during an active demo window | Team 9 operations owner, with security/safety owner engaged immediately |
| P2 high | Backend 5xx threshold, AI generation failure, provider server errors or throttling; failed absolute live-quality acceptance or confirmed quality regression when drift monitoring is activated | 30 minutes during an active demo window | Team 9 operations owner, then backend or AI owner |
| P3 medium | Sustained model latency or AI CPU pressure without errors; confirmed input-distribution shift without a quality/safety failure when drift monitoring is activated | 4 business hours | Team 9 operations owner, then AI/cloud owner |

The targets are demo operating objectives, not a staffed 24-hour support commitment. Outside an announced demo window, the owner acknowledges the alert at the start of the next agreed support period. A P1 alert blocks release and continued demonstration until triage establishes a safe path.

## Response Sequence

1. Acknowledge the notification in the team incident record with its UTC time, alarm name, state change, and AWS account/Region. Never copy prompts, financial values, tokens, credentials, or Cognito claims into the record.
2. Open the `ai-financial-wellness-coach-demo-operational` CloudWatch dashboard and verify whether the alarm represents an active condition. Correlate sanitized service events by correlation ID.
3. Classify the incident as security, safety, availability, quality, cost, or false positive. Assign the backend, AI, frontend, cloud, or safety specialist without changing the primary operations owner.
4. For P1, stop promotion immediately. Isolate a compromised service or roll affected ECS services back to their last known-good immutable task definitions when applicable.
5. Preserve privacy-safe evidence: alarm history, deployment event, correlation IDs, image digest, model and prompt versions, corpus versions, and the actions taken.
6. Confirm recovery through service health, the affected alarm returning to `OK`, and the relevant smoke or evaluation gate. Do not infer recovery from an email alone.
7. Record impact, root cause, control effectiveness, owner, follow-up date, and a regression test or monitoring correction before closing the incident.

When email alerts are enabled, a missing notification requires inspection of the SNS subscription state and topic delivery metrics, re-confirmation from the team mailbox, and review of the AWS console/dashboard. A failed notification test is itself a P2 operational incident. In the current GitHub Actions reporting mode, inspect failed runs and their artifacts directly; current email delivery is not claimed.

## Drift Response

The [implemented drift workflow](model-drift-monitoring.md) uses this procedure.
Its presence in source does not establish deployed activation or delivery. See
[Operations](operations.md#drift-detection) for implemented controls and planned
activation, and [the evaluation plan](evaluation-plan.md#live-quality-baseline-and-drift-gate)
for the baseline and scoring contract. Safety or ownership failures remain P1.

1. Verify the comparison's baseline ID, model/prompt/role settings, build, corpus
   versions, dataset/evaluator hashes, completed samples and affected subgroup.
   Treat unavailable scores as incomplete evidence. Check whether a deployment,
   source change, traffic mix, evaluator change or provider outage explains it.
2. For failed quality acceptance, stop promotion; immediately contain any critical
   safety or ownership failure. For an input shift alone, review representative
   synthetic cases and task coverage before changing the model.
3. Replay failed synthetic cases with fixed trusted retrieved passages and identical
   inputs/settings. If quality recovers, inspect retrieval relevance, coverage,
   ingestion and corpus freshness. If it still fails, isolate prompt/application
   changes and compare available provider versions under the same evidence.
   Check errors, usage and timing for operational causes. An unchanged model ID
   alone cannot establish or exclude provider behavior drift.
4. Preserve aggregate comparisons, failed case/trace IDs and version identities
   under existing evidence rules. Add synthetic regression cases for new failure
   families; do not copy real user conversations or financial values into incidents.
5. Restore the last accepted configuration where applicable, or disable the affected
   behavior while resolving the cause. An ECS rollback restores application settings;
   it cannot guarantee restoration of an externally changed model alias. Verify
   recovery with both affected semantic scores and existing structural/safety gates.
6. Record cause, owner and remediation. Keep the prior baseline until the corrected
   configuration passes acceptance and a reviewed replacement baseline is approved;
   never clear an alert simply by lowering thresholds or adopting the failed run.

## Controlled Notification Test

This optional procedure applies when email alerts are restored. After the AWS confirmation email has been accepted, run:

```powershell
.\infra\scripts\test_operational_alert.ps1 `
  -ExpectedEndpoint <confirmed-team-email> `
  -Confirmation TEST-OPERATIONAL-ALERT
```

The script refuses to run without a confirmed email subscription, refuses to override an alarm that is already genuinely in `ALARM`, verifies that the alarm targets the managed SNS topic, temporarily exercises the CloudWatch alarm action, verifies the successful SNS action in alarm history, restores the original state, and writes a privacy-safe artifact under `artifacts/`. It deliberately cannot assert inbox delivery. A recipient must acknowledge the received test message before governance records describe delivery as verified.

When email delivery is in scope, repeat the controlled test after changing the topic, subscription, alarm action, or operational owner, and at least once before a formally assessed demonstration that claims email delivery.
