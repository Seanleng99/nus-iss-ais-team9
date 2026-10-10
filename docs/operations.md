# Operations And Monitoring

## Demo Objectives

These are initial targets to validate with AWS load evidence, not production guarantees.

| Signal | Initial objective | Release/alert action |
|---|---:|---|
| Backend availability | 99.5% during demo window | Alarm on 5-minute error rate above 2% |
| Non-model backend P95 | Under 1 second | Investigate sustained breach for 15 minutes |
| End-to-end coaching P95 | Under 8 seconds | Review OpenAI request latency, retries, and scaling |
| Critical safety block rate | 100% on approved eval set | Block release immediately |
| Retrieval recall@3 | At least 85% | Block release or restore source/index version |
| Missing correlation IDs | 0 | Alert and treat affected audit trail as incomplete |

## Telemetry

Application access events contain service, correlation ID, method, path, status, and duration. They do not contain request bodies, financial values, API keys, bearer tokens, OIDC claims, or model prompts. The AI service additionally emits `service.ai.workflow` JSON lifecycle events for workflow start/completion/failure, guardrails, routing, task start/completion, synthesis, Compliance, canonical retrieval topics and chunk counts, total duration, and model-call/token counts. Detail fields are allowlisted and error/reason codes are restricted to bounded token values. These logs never contain the raw question, user/profile/session identifiers, retrieved text, model output, provider message, or financial snapshot. AI response audit metadata includes the server trace ID, UTC execution time, selected agents, task timing and attempts, dependency edges, guardrail categories, model/prompt identity, model-call duration, token usage, retrieval corpus versions, and source/version/checksum/review tuples. The backend persists the trace against the owner-bound profile session without raw prompts, retrieved text, identity claims, or financial grounding.

Each workflow receives a server-generated UUID trace ID, independent of the caller's correlation ID, so repeated client headers cannot collide with persisted traces. `X-Correlation-ID` remains a diagnostic link across service headers and logs; accepted values contain 1–128 ASCII letters, digits, underscores, dots, or hyphens and start with a letter or digit. Invalid values are replaced with a UUID. AI workflow logs carry both IDs; response audit metadata carries the trace ID.

Education diagnostics distinguish retrieval from subsequent evidence assessment. `education.answerability.rejected` records fixed reason codes for invalid subquestion coverage, missing support/limitations, invalid passage references and quotes absent from carried evidence. `education.coverage.assessed` records assessment status, semantic failure code and source/topic counts without questions, quotations or model wording. An accepted retrieval followed by `INVALID_EDUCATION_PROVENANCE` requires inspecting answerability contracts before changing the corpus or token limit.

All model-review blocks now require a category and brief explanation. After one failed correction, an invalid verdict fails closed as `review_contract_unverified`; it is distinct from a valid `model_review` block. `compliance.completed.review_block_categories` carries bounded categories for ordinary Budget/Goal reviews as well as Education reviews. Optional source gaps can produce qualified partial responses while verified calculations remain visible; this does not authorize unsupported citations or financial recommendations.

`education.completeness.repair_decision` reports every failed admission check in `repair_blockers` and the first as `reason_code`. Evidence, specialist eligibility and unknown usage are reported separately from `REPAIR_TOKEN_BUDGET_EXCEEDED`, `REPAIR_CALL_BUDGET_EXCEEDED` and `REPAIR_DEADLINE_EXCEEDED`. Numeric `used_tokens`, `estimated_repair_tokens`, `token_limit` and `remaining_tokens` explain the forecast without logging prompts or review feedback. The forecast counts all consumed calls but estimates only the latest Education writer and full reviewer pair; combined read-only responses preserve specialist text and do not need another synthesis call. A denied correction leaves the original independently reviewed result in place. `education.completeness.repair_unavailable` retains a sanitized `error_code`, including provider or token failures, while the original review remains visible. Increasing a token limit does not remedy a missing evidence seal, prohibited request or deadline.

Education and financial repair decisions also carry numeric
`estimated_repair_duration_ms` and `remaining_duration_ms`. Admission reserves
two observed call durations per affected role for its correction and possible
contract retry; an unseen role uses the slowest observed call in that workflow.
These are forecasts, not latency guarantees. A positive remaining deadline no
longer suffices by itself. If the projected work cannot fit, the reviewed veto
remains withheld with `REPAIR_DEADLINE_EXCEEDED`; no extra repair call begins.
The existing hard workflow, token and call limits still apply to admitted work.

Local synthetic checks on 6 October replayed the saved-goal education follow-up and combined December affordability/education request against GPT-6 Luna and the approved local document retrievers. Both passed independent review: the follow-up used 27,915 tokens across five calls; the combined request used 31,601 across seven. A preceding combined replay exposed contradictory missing-data statements from specialists whose role-scoped context intentionally omitted another role's evidence. Writers now answer their assigned part without converting that omission into an answer-wide limitation. These are local model checks, not deployed HTTP/browser acceptance. Regression coverage separately forces a qualification correction, verifies unchanged financial results and sealed education evidence, and checks that rejected or unavailable corrections remain withheld with diagnostic recovery intact.

Each orchestration run defaults to an 80,000-token aggregate model budget, counting both input and output across all model calls. The 6 October source change increases the ceiling to leave headroom for combined requests, contract correction and one bounded Education correction. Application defaults, `.env.example`, the AWS template and release overrides agree on `MAX_MODEL_TOKENS_PER_RUN=80000`; release verification rejects an inherited stale limit. The application loads the single packaged current prompt contract (manifest release v10) and rejects mismatched prompt assertions at startup. Application defaults load the packaged role policy: Budget/Goal/Spending medium/3,200, Education medium/4,000 and Compliance medium/3,000. Release applies and verifies those settings; deployment smoke checks the observed Budget and reviewer telemetry. Per-role output limits, call limits and deadlines remain enforced. Monitor token usage, latency and budget failures with representative conversations. Model calls reserve a call slot before provider invocation, so concurrent calls count against the same call limit. A recorded token overrun fails closed with the privacy-safe `MODEL_TOKEN_BUDGET_EXCEEDED` error code and `model_budget` component; once recorded usage reaches the token budget, no further call starts. The OpenAI gateway counts complete provider input and atomically reserves input plus maximum output before invocation, including parallel calls. It reconciles measured usage after completion; unknown usage prevents further model calls. Backend database-backed per-principal quotas additionally reserve 80,000 tokens per request, default to 30 requests per fixed UTC minute, two concurrent requests and 2,000,000 tokens per fixed UTC hour. These are token/admission controls, not a global currency or billing cap. Telemetry retains active traces only; closed workflows reject late calls and ignore late completions without recreating state.

The conditional Education release smoke requests a read-only illustrative Budget baseline, then verifies approved contexts, pinned source versions, the Budget retrieval consumer, the governed tool dependency and the persisted trace. Requests to create a monthly plan enter budget drafting and do not exercise this analysis capability. For recognized topics, semantic calendar routing preserves conditional Budget/Goal evidence access without adding a full Investment Education narrative; draft capture and topics outside the conditional detector still require the Education specialist. These controls keep the smoke meaningful within the existing model-token limit.

Release `37310200156` for `8310a98` on 5 October 2026 deployed healthy services but failed conditional Education smoke and rolled back. CloudWatch trace `183798d4-5010-4c34-b89f-13c97e8ca4a4` recorded seven model calls consuming 40,299 tokens; independent Compliance crossed the unchanged 40,000-token limit. Passage validation succeeded in that trace. The recovery removes duplicate answerability text and references coverage quotations already carried in writer/reviewer passages. The smoke asks for the Budget calculation and public definitions separately, retaining strict grounded-evidence, corpus, dependency and persisted-trace checks. It does not demand that educational passages establish a personalized relationship to the calculated capacity.

Local recovery verification on 5 October: 1,719 AI tests passed with one Windows symlink-privilege skip; all 42 release-smoke contract tests, eight offline evaluation suites and Ruff passed. A fresh local GPT-6 Luna request using the approved document retrievers supported both public definitions, passed independent Compliance and consumed 22,471 tokens across six calls. That check did not exercise deployed HTTP services or the smoke profile's existing dialogue; AWS release smoke remains the deployment verification.

Release `37323605695` for `d81f52c` failed the same conditional smoke and rolled back. Its final token-overrun trace `f08cfaed-2747-489e-a490-4a7dc0951ce6` consumed 40,114 tokens; backend logs confirmed eight prior messages loaded from the fixed smoke session. Each authenticated smoke attempt now uses a fresh UUID-suffixed session, including retries, so deployment verification does not inherit earlier release dialogue. Synthetic user IDs and all evidence assertions remain unchanged.

A fresh request built through the backend also exposed routing ambiguity: an income/capacity calculation was treated as budget drafting. Router instructions now distinguish calculations using supplied income/expenses from category planning and saved-record commands, including compound educational questions. A local GPT-6 Luna check with that backend-built request routed to Budget analysis, grounded both definitions, passed independent Compliance and consumed 26,946 tokens across seven calls. It used approved local document retrievers; deployed HTTP smoke remains the release gate.

Follow-up verification: 1,719 AI tests passed with the same Windows symlink skip, all 42 smoke contract tests passed, and all seven corpus release tests passed using Git Bash. Ruff and whitespace checks passed.

Release [37434817582](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/37434817582) for `bd3888a` on 6 October 2026 deployed healthy services but failed the basic model smoke with `agent_budget model-call telemetry was absent` and rolled back successfully. CloudWatch trace `d763973e-86d0-4c46-baff-2da07f6e98b6` shows the request to create a monthly budget invoked `budget_capture`; that drafting path does not require the narrative Budget writer. The rendered AI task had v8, the 80,000-token ceiling and the recommended reasoning/output policies. The failure was a mismatch between the probe's request and its required role, rather than stale task settings.

The basic model probe asks only for monthly disposable income from known synthetic income and one explicitly monthly recurring expense. It pins the calculation month and creates a fresh synthetic user and session for every attempt, so saved profiles, plans and earlier dialogue cannot replace its inputs. It checks SGD 4,000 minus SGD 1,500 equals SGD 2,500, requires `agent_budget`, and verifies the packaged current prompt release and canonical reasoning/output limits in both response telemetry and the owner-scoped persisted trace. Budget drafting, incorrect calculations and stale role policies still fail the gate. Changing release source does not establish that the deployed task has been updated; deployment needs its own verification.

At the 6 October checkpoint, the corrected probe passed through isolated local backend/AI HTTP services and persisted SQLite traces using both the offline fixture and real GPT-6 Luna. The real-model request used 12,358 tokens across five calls, returned SGD 2,500, and retained Budget medium/3,200 and Compliance medium/3,000 in both response and saved trace. All 278 infrastructure regressions passed (five skipped; four subtests passed), including 49 smoke contracts; Ruff and whitespace checks passed. This recorded check verified the probe locally. Later release evidence is recorded separately in [operational evidence](operational-evidence.md); it does not replace a complete current-model browser acceptance run.

In AWS, ECS stdout/stderr is sent to CloudWatch log groups with 30-day retention. Restrict log access separately from application access. The foundation enables ECS Container Insights. The application stack creates the `ai-financial-wellness-coach-demo-operational` dashboard for ECS CPU/memory, ALB backend errors/health/latency, and privacy-safe AI generation-failure counts. Model latency and token usage are recorded in application evaluation telemetry.

## Alerts

- ALB/backend target 5xx count and target-health loss.
- ECS deployment failure events through EventBridge and SNS.
- AI service sustained CPU pressure and increased end-to-end model latency.
- OpenAI throttling or server errors surfaced through sanitized generation-failure telemetry.
- Privacy-safe AI model/retrieval generation failures derived from logs.
- Sanitized OIDC/authorization failure spike or prompt-injection spike.
- Critical/high Inspector finding after deployment.
- Scheduled evaluation failure or metric regression.
- Education RAG manifest, freshness, checksum, ingestion, or deployed-object drift.

The first five controls are provisioned by `infra/aws/demo-application.yaml`; the remaining controls require an approved metric definition or existing security service integration. Pass `-AlertEmail address@example.com` to the bootstrap script to create an email subscription, then confirm the SNS subscription. The weekly operational workflow verifies that at least one confirmed email subscription remains, without retaining the address in its artifact. Without a confirmed endpoint, alarms still change state and publish to the topic but do not notify a person.

## Database Changes

The 2026-09-14 availability incident was caused by the RDS-managed password rotating
after the backend task started. ECS-injected environment secrets stay fixed for the
task's lifetime; new database connections then failed authentication. A rolling
restart of the same backend image restored database access. The bounded recovery
run returned 13/13 normal HTTP responses with complete synthetic-session cleanup;
12/13 answer checks passed on the existing v5 deployment. Recovery is not a quality
acceptance or deployment of the changes below.

The backend supports opt-in runtime credential refresh with `POSTGRES_SECRET_ARN`,
an explicit `POSTGRES_HOST`, and `AWS_REGION`. Each new physical PostgreSQL connection,
including online Alembic migrations, fetches the secret's `AWSCURRENT` username and
password. Already pooled connections do not fetch on every query. Secret lookup
failures fail closed with a generic error; no secret is logged. Static local
credentials continue to work when the ARN is absent. Offline migrations do not
contact AWS. See [ECS secret refresh behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html)
and [SQLAlchemy connection hooks](https://docs.sqlalchemy.org/en/21/core/engines.html#controlling-how-parameters-are-passed-to-the-dbapi-connect-function).

Activation requires a reviewed release containing this backend implementation:

1. Apply the foundation template and retain its new `BackendTaskRoleArn` output.
   The dedicated role can read only the RDS-managed database secret; the shared
   frontend application role receives no database-secret permission.
2. Update the GitHub OIDC stack with `EcsBackendTaskRoleArn` set to that output.
   `update_github_oidc.ps1` passes it when present. `iam:PassRole` stays limited to
   the named task roles and the ECS task service.
3. Apply the application template with `BackendTaskRoleArn` and a compatible
   backend image. This enables runtime lookup and removes the startup username and
   password injection. For a fresh bootstrap, use `-EnableDatabaseCredentialRefresh`.
   Existing stack updates preserve the optional parameter when it is omitted.
4. Run migrations and the authenticated persistence smoke test, then the live
   evaluation and cleanup checks. Check database access again after the next
   scheduled secret rotation. Unit tests simulate rotation; they do not replace
   this live verification.

The 2026-09-14 repair did **not** apply these IAM or application changes. Until
activation, another rotation can cause the same failure. If activation must be
rolled back, explicitly clear `BackendTaskRoleArn` while restoring the prior image,
so ECS resumes injecting current static credentials. Do not remove runtime lookup
while leaving an image without injected credentials. Do not rotate the database
password merely to test the repair on the live demo.

CI applies every Alembic migration to PostgreSQL and runs `alembic check` for model drift. Every backend release runs `alembic upgrade head` as one ECS task before updating the backend service, even when the change manifest did not identify a migration-file edit. This makes the database revision a deployment invariant instead of relying solely on path classification. Treat migration failure as a failed release. Use expand-and-contract changes because rolling back an ECS task definition does not reverse a successful schema migration.

Policy `data-lifecycle-v1` keeps orchestration traces for 30 days, chat history for 90 days, and inactive allowlisted synthetic automation users for 30 days. The weekly AWS operational workflow runs `python -m app.jobs.purge_data_lifecycle` as a one-shot task against the current backend task definition. OIDC-bound users and unowned identifiers outside the automation namespace are excluded from automatic user expiry. Owner-scoped export and complete workspace deletion are available through the backend and `Privacy & data` UI; individual trace and chat removal also remain available. Monitor aggregate purge counts and rejected cross-profile operations without logging IDs or request content. See `docs/data-lifecycle.md`.

Route deployment failures through EventBridge and operational alerts through SNS or the team incident channel. Every alert needs an owner, severity, runbook link, and tested notification path. `docs/operational-alert-runbook.md` assigns the Team 9 operations owner, severity-specific response targets, specialist escalation, privacy-safe evidence requirements, and the controlled notification-test procedure.

## Drift Detection

Drift observation is partially implemented. Weekly CI reruns fixed datasets against
versioned offline fixture baselines; acceptance fails on an absolute threshold
breach or excessive regression. This detects application regressions, not changes
in live model semantics. AWS Operational Validation runs weekly on Sunday at 10:00
Singapore time and on demand, using repeated synthetic sessions against the deployed
model, prompts, orchestrator and retrieval. Its structural, latency and estimated-cost
gates do not replace calibrated answer-quality scoring. Dedicated quality capture,
baseline comparison, aggregate input queries and SNS reporting now have executable
scripts and an opt-in Sunday 10:15 Singapore workflow. Deployment and an accepted
baseline remain activation gates; optional email reporting additionally requires
notification verification. GitHub-only monitoring retains summaries and artifacts.
Existing CloudWatch
generation-failure alarms remain separate operational signals. See
[Model drift monitoring](model-drift-monitoring.md) for setup and commands.

The 2026-10-10 [activation evidence](evaluation-evidence/model-drift-activation-2026-10-10.json)
records a successful code release and provider-model metadata verification, with
GitHub-only reporting configured. The evaluator secret has since been added, and
drift policy version 3 uses a provisional 60-second complete-answer P95 based on
recorded GPT-6 Luna timings. The original smoke evidence retains its historical
10-second threshold. Scheduling remains disabled until the new credential succeeds
and a complete passing capture is independently reviewed and accepted. The new
secret's earlier GPT-6 Sol preflight returned HTTP 403 before any app requests.
Current configuration uses GPT-6 Luna for generation and separate rubric grading,
with mandatory independent human calibration. See
[candidate activation evidence](evaluation-evidence/model-drift-candidate-2026-10-10.json).
Luna grading access is now verified. The corrected capture remains incomplete and
failed quality/usage acceptance; a separate Education diagnostic returned no
approved citations. These failures keep scheduling disabled and cannot establish
confirmed relative drift without an accepted baseline.

The weekly RAG governance job checks both reviewed manifests and exact local
documents, then audits both Bedrock Knowledge Bases and their S3 objects for
checksums, approval, provenance, review deadlines and completed ingestion. Release
ingests and audits both approved corpora before activating their version pins;
any issue blocks corpus promotion. These controls detect source/configuration
changes but do not establish retrieval relevance or generated-answer groundedness.

| Signal | Measurements | Interpretation and current status |
|---|---|---|
| Live answer quality | Financial correctness, routing/dependencies, groundedness, citation support, unsafe advice, false refusal and explanation/language quality | Same-model boolean scoring with independent human calibration and overall/specialist/language/intent baseline comparison are implemented; first reviewed baseline and scheduled activation remain pending. |
| Input distribution | Capture/analysis intent, selected-agent shares, language, missing-input rate and message-length bands | Regular and streamed completed requests emit bounded buckets; optional server-side aggregate queries and marginal distribution comparison are implemented. Production activation remains subject to data review. |
| Retrieval | Relevant-source recall, evidence gaps, source frequency/age, corpus versions and provenance | Offline retrieval gates, runtime diagnostics and corpus audits exist; the new judge checks citation support against approved reference documents. Exact retrieved-passage replay and recurring live retrieval recall remain separate work. |
| Execution | Provider errors/retries, review/repair failures, P95 latency, model-call/token use and estimated cost per request | Telemetry and selected alarms/live limits exist. Compare within similar tasks and configurations before attributing a change to the model. |

Use the versioned baseline and scoring contract in
[the evaluation plan](evaluation-plan.md#live-quality-baseline-and-drift-gate).
Keep the frozen quality benchmark and its approved baseline alongside a separate
monitor of changing runtime traffic. Increased Compliance blocks, evidence gaps or
negative feedback are investigation signals; they do not independently label an
answer incorrect, and model self-reported confidence is not a calibrated drift metric.

After production-data approval, the proposed input monitor compares the latest
seven complete UTC days with an approved, non-overlapping 21-day reference period,
fitting the existing 30-day log retention. The collector verifies adequate retention
and filters to the current model/effective prompt. It compares fixed marginal
intent/language/length/agent/missing-input/blocked buckets; conditional live cohorts
are not implemented. Quality benchmark scores separately report specialist, intent
and language strata. Use Jensen-Shannon divergence and calibrate
its threshold and minimum sample counts from ordinary variation. Rare strata with
too few observations are marked insufficient evidence and can use a longer window.
The demo should use synthetic runs to validate the job and notification path before
activation for real traffic. A change in traffic mix alone must not trigger model
replacement or rollback.

Retain only purpose-limited aggregates: intent/agent shares, missing-input and
guardrail-category rates, language/length bands, retrieval source frequency/age,
latency, token use and coded user feedback. Do not add raw prompts, answers,
financial amounts, personal identifiers or free-text feedback to drift logs.
Suppress small aggregate cells, restrict access and define aggregate retention
before activation. Existing 30-day logs/traces and 90-day operational evidence
retention do not automatically authorize a new production data store.

The opt-in monitor alerts on sustained ordinary relative-quality regression or
eligible input-distribution shifts across two consecutive scheduled comparisons.
Critical safety/ownership failures and absolute acceptance failures do not wait for
confirmation. A missing or incomplete evaluation is an evidence failure, not a green
quality result. Every notification carries the baseline/current versions, window,
metric and subgroup, counts, threshold, case IDs where applicable, severity, owner
and [response procedure](operational-alert-runbook.md#drift-response). SNS/email
delivery must be exercised for the new alert source before it is described as active.
Investigate first, then make a reviewed prompt, retrieval, application or model
change supported by a new regression case and completed acceptance evidence.

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

The `AWS Operational Validation` workflow performs this load test, three repetitions of the live OpenAI/RAG suite, governed lifecycle retention, dashboard/alarm verification, and autoscaling verification each week. The live RAG cases require citations and persisted traces to match the configured corpus pin. A manual run can also force and verify one backend task replacement. The first retained AWS artifact recorded 100 percent case and load success, 7.32-second live P95, 4.85-second load P95, and zero chat-session cleanup failures **for the earlier Bedrock deployment**. GPT-6 Luna needs new live evidence. The default gates remain 10 seconds for live P95, 8 seconds for load P95, and USD 0.05 estimated live-evaluation cost. A failed-deployment rollback remains separately demonstrated by the release workflow and ECS circuit breaker.

A controlled test on 2026-08-30 verified the CloudWatch-to-SNS action, restored the alarm to `OK`, and received human acknowledgement of both the `ALARM` and restoration emails. That is historical delivery evidence. The 2026-10-10 activation check found zero confirmed or pending subscriptions on the operational topic, so current email delivery is unavailable. Model drift reporting is configured for GitHub Actions summaries and artifacts at the user's request. Use `infra/scripts/test_operational_alert.ps1` after restoring and confirming an email subscription. Ownership, severity, response targets, and recovery steps are defined in `docs/operational-alert-runbook.md`.

## Incident And Rollback Procedure

1. Stop promotion and classify whether the incident is security, safety, availability, quality, or cost related.
2. Preserve correlation IDs, sanitized logs, deployment events, image digest, model ID, prompt version, policy version, and source version.
3. Rotate affected credentials and isolate a compromised service when applicable.
4. Roll back all affected ECS task definitions to the last known-good revisions.
5. Add a regression case before releasing the correction.
6. Record impact, root cause, control effectiveness, owner, and follow-up date.
