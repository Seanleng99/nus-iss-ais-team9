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

Application access events contain service, correlation ID, method, path, status, and duration. They do not contain request bodies, financial values, API keys, or model prompts. AI response audit metadata includes trace and correlation IDs, UTC execution time, selected agents, task timing and attempts, dependency edges, guardrail categories, model/prompt identity, model-call duration, and token usage. The backend persists the trace against the profile-scoped chat message without raw prompts or financial grounding.

In AWS, send ECS stdout/stderr to encrypted CloudWatch log groups with explicit retention. Restrict log access separately from application access. Enable ECS Container Insights and collect ALB request/error/latency metrics, ECS CPU/memory/task count, Bedrock invocation latency/errors/token usage, RDS health, and vector-store health.

## Alerts

- ALB/backend 5xx rate or target-health loss.
- ECS service below desired task count or deployment failure event.
- P95 latency above objective.
- Bedrock throttling, invocation errors, or daily cost anomaly.
- Authentication failure spike or prompt-injection spike.
- Critical/high Inspector finding after deployment.
- Scheduled evaluation failure or metric regression.
- RAG source freshness/checksum failure after ingestion exists.

## Database Changes

CI applies every Alembic migration to PostgreSQL and runs `alembic check` for model drift. Every backend release runs `alembic upgrade head` as one ECS task before updating the backend service, even when the change manifest did not identify a migration-file edit. This makes the database revision a deployment invariant instead of relying solely on path classification. Treat migration failure as a failed release. Use expand-and-contract changes because rolling back an ECS task definition does not reverse a successful schema migration.

Apply explicit retention and deletion policy to orchestration traces before using real financial data. Trace lookup is profile-isolated at the backend boundary; monitor missing traces and rejected cross-profile lookups without logging request content.

Route deployment failures through EventBridge and operational alerts through SNS or the team incident channel. Every alert needs an owner, severity, runbook link, and tested notification path.

## Drift Detection

The weekly GitHub Actions evaluation reruns fixed datasets and compares metrics with versioned policy baselines. A release fails on either an absolute threshold breach or excessive regression.

After approved production telemetry exists, observe only privacy-preserving aggregates: intent distribution, selected-agent distribution, missing-input rate, message-length bands, guardrail category rate, retrieval source frequency, source age, latency, token use, and user feedback. Do not retain raw prompts merely to measure drift. A sustained distribution shift triggers dataset review first, followed by prompt, retrieval, or model changes; fine-tuning is considered only when simpler mitigations fail.

## Scalability And Reliability Exercise

Run the bounded smoke utility against the backend with synthetic data:

```powershell
python infra/scripts/load_smoke.py `
  --url https://BACKEND/api/coach `
  --api-key $env:SMOKE_BACKEND_API_KEY `
  --requests 100 --concurrency 10 `
  --maximum-p95-ms 8000
```

Record commit SHA, task sizes/counts, model/profile, concurrency, success rate, P50/P95/P99, throttles, errors, and estimated cost. Use the result to set ECS target-tracking policies and Bedrock quotas. Demonstrate one task replacement and one failed deployment rollback as reliability evidence.

## Incident And Rollback Procedure

1. Stop promotion and classify whether the incident is security, safety, availability, quality, or cost related.
2. Preserve correlation IDs, sanitized logs, deployment events, image digest, model ID, prompt version, policy version, and source version.
3. Rotate affected credentials and isolate a compromised service when applicable.
4. Roll back all affected ECS task definitions to the last known-good revisions.
5. Add a regression case before releasing the correction.
6. Record impact, root cause, control effectiveness, owner, and follow-up date.
