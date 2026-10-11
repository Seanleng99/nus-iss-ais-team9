# AI security hardening — 10 October 2026

The workspace now has stronger application-enforced AI controls. The changes
address the confirmed preference privacy leak and add aggregate abuse limits.
They do not establish production readiness. The coordinated database migration
and application deployment subsequently passed for `80c3482`; see the
[deployment evidence in the risk register](security-risk-register.md#deployment-and-validation-evidence).
That release did not establish quota-alarm activation, cross-replica behavior
or complete live-matrix acceptance. On 11 October, a scoped stack repair activated
the quota-denial filter/alarm, and operational runs verified all five required
alarms, edge controls and retention. The token metric/dashboard additions and
cross-replica behavior remain separately unverified; full live acceptance remains
incomplete. See [operational evidence](operational-evidence.md#operational-alert-notification).
The local and bounded live results below retain their original scope.

## Changes

| Area | Implemented behavior |
|---|---|
| Outbound preferences | Keep the inspected, redacted string instead of the original value. Inspect each allowed list element; retain bounded numeric/boolean preferences. |
| Other model context | Apply one recursive privacy boundary to transaction descriptions/categories, goal names, arbitrary context keys/values, pending drafts, history, summaries, observations and referents. Quarantine recognized stored instructions while retaining a benign current question. |
| Financial integrity | Preserve schema-validated numeric/date facts and native monetary values. Hash sensitive obligation IDs consistently so redaction cannot merge distinct financial obligations or break their references. |
| Secondary model calls | Apply the same boundary to post-action composition and sanitize reviewed specialist/outcome evidence before composing and reviewing it. |
| Obfuscated PII | Inspect normalized compatibility characters and invisible separators before applying the existing email, Singapore phone, NRIC-like and card-like patterns. |
| Aggregate limits | Persist a shared authenticated-principal ledger and concurrency leases in PostgreSQL. Authorize ownership first; reject excess coaching requests before chat creation or model work, using HTTP 429 and `Retry-After`. |
| Accounting failures | Reserve the full per-run token allowance upfront. Refund unused tokens only with a complete, internally consistent usage audit. Retain both the reservation and lease when a timeout/cancellation can leave model work running. A completed call with missing token usage frees concurrency while keeping its token reservation. |
| Per-call admission | Count the complete OpenAI input, including its output schema, and atomically reserve that count plus the maximum output allowance before inference. Parallel calls cannot spend the same remaining budget. Unknown prior usage prevents post-action composition. |
| Monitoring | Record fixed reason codes and content-free token totals. Add CloudWatch quota-denial/token metrics, a denial alarm and dashboard series. The existing retention job removes idle pseudonymous ledgers after more than 48 hours. |
| Evaluation | Expand to 43 case definitions and 102 provider evaluations per trial, including English/Chinese, paraphrases, multi-turn context, malicious stored labels/preferences and retrieval variants. Privacy cases inspect actual outgoing prompts without saving their content. |
| Live regression | Use the same project provider and local JavaScript grader for repeated live trials. Reserve aggregate tokens across parallel model calls, stop on unknown usage/budget exhaustion, retain checkpoints and fail incomplete evaluations. Future runs record case/grader hashes and abort if the grader changes. |

Defaults are 30 coaching requests per fixed UTC minute, two concurrent requests,
and two million input/output/reasoning tokens per fixed UTC hour for each
authenticated principal. All profiles and conversations under the same identity
share a bucket. Automation requests share one credential bucket. The database
clock supplies window boundaries across replicas. Fixed windows allow bursts
across a boundary; concurrency and token reservations remain independently bounded.

The backend reservation is 80,000 tokens per request and must match
`MAX_MODEL_TOKENS_PER_RUN` on the AI service, including post-action composition.
Deployment configuration tests verify that alignment. These limits are token
controls, not a currency-denominated billing cap.

Input counting adds a provider request before inference. The initial hardening
used a three-second timeout; current source permits one retry after a typed
timeout, connection or server failure, with three- and five-second attempt limits
inside an eight-second local budget and the remaining workflow deadline.
Invalid counts and access failures do not retry, and generation keeps SDK retries
disabled. Failure to establish the count fails closed. The SDK requirement is
OpenAI 2.54 or later. The count and generation
use the same model, instructions, input, reasoning policy and output schema;
tests verify those fields agree. OpenAI documents the
[input-counting endpoint](https://developers.openai.com/api/docs/guides/token-counting).

## Validation

- Full backend suite after the ownership/quota ordering correction: **957 passed**.
- Full AI suite: **1,941 passed, 1 live-only test skipped**. After the final
  source-metadata privacy change, **24 privacy/composition/reservation tests passed**.
- Infrastructure/provider/report selection: **86 tests and 6 subtests passed**.
- Shared trace contract: **16 passed**.
- Local JavaScript grader: **12 passed**.
- Actual offline Promptfoo CLI: **102 passed, zero failures/errors**.
- Repeated offline project-provider run: **204 passed** across two trials.
- Ruff checks and CloudFormation lint pass. Alembic generated the new PostgreSQL
  migration SQL successfully; no live database migration was applied.

Workspace evidence is retained under `artifacts/security-hardening`. The live
evaluation uses GPT-6 Luna and packaged prompt contract v10, with governed local
documents and synthetic injected retrieval fixtures. Its model and prompt hashes
are retained in individual results. It does not exercise the deployed AWS
application, Bedrock retrieval, authentication or persisted user sessions.

The inherited credential failed authentication in the first attempt; no successful
inference occurred. The subsequent runs used the project's credential file without
printing or persisting the key.

| Live run | Planned | Result records | Passed | Failed | Errors | Conservative charged tokens | Gate |
|---|---:|---:|---:|---:|---:|---:|---|
| Broad matrix, before per-call input reservations | 204 | 102 | 96 | 5 | 1 | 758,963 | Incomplete, failed |
| Scoped follow-up with input reservations | 8 | 8 | 5 | 2 | 1 | 160,878 | Incomplete, failed |
| Corrected educational control | 2 | 2 | 1 | 0 | 1 | 6,735 | Incomplete, failed |

The broad matrix stopped when a model response had unknown usage; its second
trial did not run. Its failures included a clean educational candidate rejected
by compliance, an injected-preference budget answer that failed relevance, and a
multi-turn benign control that requested more input. Two failures involved
required literal terms despite relevant budget explanations; those grader
limitations are retained as failures and need review. The retrieval case at the
stop returned `MODEL_USAGE_UNKNOWN`, rather than a validated answer.

The follow-up verified successful real input-counting calls and repeated the
preference privacy case through both the router and Budget: **four of four passed**.
The original educational candidate was rejected in both trials. The invisible
retrieval-instruction case passed its first trial; the second stopped before its
next model call when the remaining evaluation budget could not cover the
conservative reservation. Eight result records therefore do not mean eight
completed evaluations. Both runs correctly return a failing gate.

Investigation of the candidate refusals found an invalid control payload: it
omitted the application's required model-knowledge disclosure and provenance.
The reviewer explicitly identified that omission. The test now uses the actual
Education renderer and section metadata. The corrected control passed its first
live trial; the aggregate token cap prevented the second inference. Earlier
failed controls remain in the evidence, but they do not establish an application
false-refusal defect. No guardrail or grading criterion was relaxed to obtain the
corrected pass. The other relevance, clarification and lexical findings still
require review.

No tested outbound privacy canary leaked, and no confirmed attack bypass was
observed among completed checks. Incomplete trials, usefulness failures and the
limited attack set prevent a broader safety claim. Including the conservative
reservation for the failed authentication attempt, aggregate charged tokens were
**953,762**, below the one-million-token bound; this is not an actual billing total.
The full matrix may need a larger explicitly approved future budget to finish
two trials; the current workflow stops and fails instead of exceeding its cap.

The [machine-readable evidence](evaluation-evidence/ai-security-hardening-2026-10-10.json)
retains model/prompt identities, case/grader hashes, test summaries and complete
synthetic live results. The [live result tables](evaluation-evidence/ai-security-hardening-live-2026-10-10.md)
show questions, responses, cohort statistics and failures. Current source hashes
describe the final workspace; the broad live run predates the input-reservation
change and is explicitly identified that way.

## Rollout and remaining work

1. Completed for `80c3482`: Alembic revision `20261010_0018` and coordinated
   application images deployed. Missing quota tables still fail coaching closed
   with HTTP 503 on any future environment.
2. Quota-denial filter/alarm activation was verified on 11 October. Verify the
   remaining token metric/dashboard resources and keep token reservation settings aligned.
3. Verify concurrent requests across at least two backend replicas with an
   authenticated synthetic principal; confirm 429, expiry, usage reconciliation,
   ownership isolation, alarms and the scheduled retention job.
4. Require review of live safety, useful completion, false refusals and provider
   errors after changing a model, prompt policy or approved corpus. The existing
   CI security scan runs automatically after relevant changes. Paid release
   security runs only when `RUN_LIVE_SECURITY=true`; it defaults off and then
   requires the full two-trial matrix. The bounded local CLI remains available.
   See [post-deployment acceptance](post-deployment-acceptance.md).
5. Repeat the corrected educational control and investigate relevance/clarification
   failures, review lexical grader limitations, and finish the full repeated live
   matrix before claiming readiness for real-user financial data.

Database concurrency tests use independent controllers against a file-backed
SQLite database, and PostgreSQL locking/upsert SQL is generated. Docker's local
PostgreSQL daemon is unavailable, so PostgreSQL concurrency and deployed replica
behavior remain rollout checks. Deployment and cloud alarm activation were not
performed as part of the original 10 October workspace validation; the later
milestones are recorded above.

Pattern redaction cannot recognize all personal names, addresses, secrets or
encoded disclosures. The model and its separate compliance call can share blind
spots. Deterministic controls remain necessary, and unseen semantic injections,
broader financial factuality, anonymous registration abuse, global spend ceilings
and public-endpoint denial of service need further evidence before real-user use.
