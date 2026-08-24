# Operations And Monitoring

## Demo Objectives

These are initial targets to validate with AWS load evidence, not production guarantees.

| Signal | Initial objective | Release/alert action |
|---|---:|---|
| Backend availability | 99.5% during demo window | Alarm on 5-minute error rate above 2% |
| Non-model backend P95 | Under 1 second | Investigate sustained breach for 15 minutes |
| End-to-end coaching P95 | Under 8 seconds | Review Bedrock latency, retries, and scaling |
| Critical safety block rate | 100% on approved eval set | Block release immediately |
| Retrieval recall@3 | At least 85% | Block release or restore source/index version |
| Missing correlation IDs | 0 | Alert and treat affected audit trail as incomplete |

## Telemetry

Application access events contain service, correlation ID, method, path, status, and duration. They do not contain request bodies, financial values, API keys, or model prompts. A failed coaching request adds only a stable error code, bounded component name, exception type, and correlation ID; it never logs the prompt, model output, provider message, or financial snapshot. AI response audit metadata includes trace and correlation IDs, UTC execution time, selected agents, task timing and attempts, dependency edges, guardrail categories, model/prompt identity, model-call duration, and token usage. The backend persists the trace against the profile-scoped chat message without raw prompts or financial grounding.

In AWS, ECS stdout/stderr is sent to CloudWatch log groups with 30-day retention. Restrict log access separately from application access. The foundation enables ECS Container Insights. The application stack creates the `ai-financial-wellness-coach-demo-operational` dashboard for ECS CPU/memory, ALB backend errors/health/latency, Bedrock invocations/errors/throttles/latency/tokens, and privacy-safe AI generation-failure counts.

## Alerts

- ALB/backend target 5xx count and target-health loss.
- ECS deployment failure events through EventBridge and SNS.
- AI service sustained CPU pressure and Bedrock P95 invocation latency.
- Bedrock throttling and invocation server errors.
- Privacy-safe AI model/retrieval generation failures derived from logs.
- Authentication failure spike or prompt-injection spike.
- Critical/high Inspector finding after deployment.
- Scheduled evaluation failure or metric regression.
- RAG source freshness/checksum failure after ingestion exists.

The first five controls are provisioned by `infra/aws/demo-application.yaml`; the remaining controls require an approved metric definition or existing security service integration. Pass `-AlertEmail address@example.com` to the bootstrap script to create an email subscription, then confirm the SNS subscription. Without an endpoint, alarms still change state and publish to the topic but do not notify a person.

## Database Changes

CI applies every Alembic migration to PostgreSQL and runs `alembic check` for model drift. Every backend release runs `alembic upgrade head` as one ECS task before updating the backend service, even when the change manifest did not identify a migration-file edit. This makes the database revision a deployment invariant instead of relying solely on path classification. Treat migration failure as a failed release. Use expand-and-contract changes because rolling back an ECS task definition does not reverse a successful schema migration.

Orchestration traces use a configurable 30-day retention period. The weekly AWS operational workflow runs `python -m app.jobs.purge_orchestration_traces` as a one-shot task against the current backend task definition. A user-scoped `DELETE /api/coach/traces/{trace_id}?user_id=...` endpoint supports individual removal, and deleting the owning chat session cascades to its traces. Lookup and deletion are profile-isolated at the backend boundary; monitor missing traces and rejected cross-profile operations without logging request content.

Route deployment failures through EventBridge and operational alerts through SNS or the team incident channel. Every alert needs an owner, severity, runbook link, and tested notification path.

## Drift Detection

The weekly GitHub Actions evaluation reruns fixed datasets and compares metrics with versioned policy baselines. A release fails on either an absolute threshold breach or excessive regression.

After approved production telemetry exists, observe only privacy-preserving aggregates: intent distribution, selected-agent distribution, missing-input rate, message-length bands, guardrail category rate, retrieval source frequency, source age, latency, token use, and user feedback. Do not retain raw prompts merely to measure drift. A sustained distribution shift triggers dataset review first, followed by prompt, retrieval, or model changes; fine-tuning is considered only when simpler mitigations fail.

## Scalability And Reliability Exercise

The application stack configures CPU target tracking at 70 percent for the backend and AI services with one to two tasks. Run the bounded smoke utility against the backend with synthetic data:

```powershell
.\.venv\Scripts\python.exe infra/scripts/load_smoke.py `
  --url https://BACKEND/api/coach `
  --api-key $env:SMOKE_BACKEND_API_KEY `
  --requests 10 --concurrency 2 `
  --maximum-p95-ms 30000 `
  --output artifacts/load-evidence.json
```

The utility deletes every synthetic chat session after measuring its request and fails if cleanup is incomplete. Its artifact records commit SHA, target host, concurrency, success rate, P50/P95/P99, failure classes, and cleanup count without prompts, answers, financial values, or credentials. Combine it with the live-evaluation token/cost artifact and captured CloudWatch/ECS state.

The `AWS Operational Validation` workflow performs this load test, repeated live Bedrock/RAG evaluation, trace-retention enforcement, dashboard/alarm verification, and autoscaling verification each week. A manual run can also force and verify one backend task replacement. Retain the first successful AWS artifact before changing this requirement from scaffolded to verified; use it to tighten latency thresholds and tune task sizing. A failed-deployment rollback remains separately demonstrated by the release workflow and ECS circuit breaker.

## Incident And Rollback Procedure

1. Stop promotion and classify whether the incident is security, safety, availability, quality, or cost related.
2. Preserve correlation IDs, sanitized logs, deployment events, image digest, model ID, prompt version, policy version, and source version.
3. Rotate affected credentials and isolate a compromised service when applicable.
4. Roll back all affected ECS task definitions to the last known-good revisions.
5. Add a regression case before releasing the correction.
6. Record impact, root cause, control effectiveness, owner, and follow-up date.
