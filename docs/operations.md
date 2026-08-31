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

Application access events contain service, correlation ID, method, path, status, and duration. They do not contain request bodies, financial values, API keys, bearer tokens, OIDC claims, or model prompts. A failed coaching request adds only a stable error code, bounded component name, exception type, and correlation ID; it never logs the prompt, model output, provider message, financial snapshot, or authentication material. AI response audit metadata includes trace and correlation IDs, UTC execution time, selected agents, task timing and attempts, dependency edges, guardrail categories, model/prompt identity, model-call duration, token usage, retrieval corpus versions, and source/version/checksum/review tuples. The backend persists the trace against the owner-bound profile session without raw prompts, retrieved text, identity claims, or financial grounding.

Each orchestration run has a 20,000-token ceiling. An overrun fails closed with the privacy-safe `MODEL_TOKEN_BUDGET_EXCEEDED` error code and `model_budget` component so operations can distinguish capacity enforcement from Bedrock, retrieval, and structured-output failures.

In AWS, ECS stdout/stderr is sent to CloudWatch log groups with 30-day retention. Restrict log access separately from application access. The foundation enables ECS Container Insights. The application stack creates the `ai-financial-wellness-coach-demo-operational` dashboard for ECS CPU/memory, ALB backend errors/health/latency, Bedrock invocations/errors/throttles/latency/tokens, and privacy-safe AI generation-failure counts.

## Alerts

- ALB/backend target 5xx count and target-health loss.
- ECS deployment failure events through EventBridge and SNS.
- AI service sustained CPU pressure and Bedrock P95 invocation latency.
- Bedrock throttling and invocation server errors.
- Privacy-safe AI model/retrieval generation failures derived from logs.
- Sanitized OIDC/authorization failure spike or prompt-injection spike.
- Critical/high Inspector finding after deployment.
- Scheduled evaluation failure or metric regression.
- Education RAG manifest, freshness, checksum, ingestion, or deployed-object drift.

The first five controls are provisioned by `infra/aws/demo-application.yaml`; the remaining controls require an approved metric definition or existing security service integration. Pass `-AlertEmail address@example.com` to the bootstrap script to create an email subscription, then confirm the SNS subscription. The weekly operational workflow verifies that at least one confirmed email subscription remains, without retaining the address in its artifact. Without a confirmed endpoint, alarms still change state and publish to the topic but do not notify a person.

## Database Changes

CI applies every Alembic migration to PostgreSQL and runs `alembic check` for model drift. Every backend release runs `alembic upgrade head` as one ECS task before updating the backend service, even when the change manifest did not identify a migration-file edit. This makes the database revision a deployment invariant instead of relying solely on path classification. Treat migration failure as a failed release. Use expand-and-contract changes because rolling back an ECS task definition does not reverse a successful schema migration.

Policy `data-lifecycle-v1` keeps orchestration traces for 30 days, chat history for 90 days, and inactive allowlisted synthetic automation users for 30 days. The weekly AWS operational workflow runs `python -m app.jobs.purge_data_lifecycle` as a one-shot task against the current backend task definition. OIDC-bound users and unowned identifiers outside the automation namespace are excluded from automatic user expiry. Owner-scoped export and complete workspace deletion are available through the backend and `Privacy & data` UI; individual trace and chat removal also remain available. Monitor aggregate purge counts and rejected cross-profile operations without logging IDs or request content. See `docs/data-lifecycle.md`.

Route deployment failures through EventBridge and operational alerts through SNS or the team incident channel. Every alert needs an owner, severity, runbook link, and tested notification path. `docs/operational-alert-runbook.md` assigns the Team 9 operations owner, severity-specific response targets, specialist escalation, privacy-safe evidence requirements, and the controlled notification-test procedure.

## Drift Detection

The weekly GitHub Actions evaluation reruns fixed datasets and compares metrics with versioned policy baselines. A release fails on either an absolute threshold breach or excessive regression. A separate weekly read-only Education governance job compares the reviewed manifest with exact S3 objects, governed sidecars, Bedrock data-source state, the latest ingestion job, checksums, withdrawals, and review deadlines; any issue fails the job and blocks corpus promotion.

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

The utility gives each independent request a unique chat-only synthetic user, deletes its chat session after measurement, and fails if cleanup is incomplete. Its artifact records commit SHA, target host, concurrency, success rate, P50/P95/P99, failure classes, and cleanup count without prompts, answers, financial values, or credentials. Combine it with the live-evaluation token/cost artifact and captured CloudWatch/ECS state.

Deleting the final chat session for a chat-only synthetic user also prunes the empty user record. PostgreSQL transaction-scoped lifecycle locks serialize same-user creation and deletion, including the boundary where the user row does not yet exist. Users with a profile, demographics, consent, transactions, goals, or budgets are never pruned by chat cleanup. This prevents weekly evaluation and load runs from accumulating empty synthetic identities.

The `AWS Operational Validation` workflow performs this load test, three repetitions of the live Bedrock/RAG suite, governed lifecycle retention, dashboard/alarm verification, and autoscaling verification each week. The live RAG cases require citations and persisted traces to match the configured corpus pin. A manual run can also force and verify one backend task replacement. The first retained AWS artifact recorded 100 percent case and load success, 7.32-second live P95, 4.85-second load P95, and zero chat-session cleanup failures. The default gates are now 10 seconds for live P95, 8 seconds for load P95, and USD 0.05 estimated live-evaluation cost. A failed-deployment rollback remains separately demonstrated by the release workflow and ECS circuit breaker.

The SNS topic, alarm actions, and managed team-mailbox subscription are deployed and confirmed. A controlled test on 2026-08-30 verified the CloudWatch-to-SNS action, restored the alarm to `OK`, and received human acknowledgement of both the `ALARM` and restoration emails. End-to-end delivery is verified. Use `infra/scripts/test_operational_alert.ps1` for repeatable tests. Ownership, severity, response targets, and recovery steps are defined in `docs/operational-alert-runbook.md`.

## Incident And Rollback Procedure

1. Stop promotion and classify whether the incident is security, safety, availability, quality, or cost related.
2. Preserve correlation IDs, sanitized logs, deployment events, image digest, model ID, prompt version, policy version, and source version.
3. Rotate affected credentials and isolate a compromised service when applicable.
4. Roll back all affected ECS task definitions to the last known-good revisions.
5. Add a regression case before releasing the correction.
6. Record impact, root cause, control effectiveness, owner, and follow-up date.
