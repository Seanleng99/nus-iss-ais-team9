# Required live release acceptance

**Release to AWS** runs live acceptance after deploying the tested current main
SHA and passing health/safety smoke. All automated checks must pass before the
release succeeds. Failure or incomplete evidence fails the release and
restores each attempted ECS service update to its captured previous task revision.
The existing workflow release lock remains held through acceptance and rollback.

## Why the former CI jobs were skipped

| Former CI job | Decision | Execution now |
|---|---|---|
| Build hardened containers | Retain before deployment | PR/manual/scheduled CI validates selected builds. Main pushes build, publish and scan immutable images in Release to AWS, avoiding a second build. Images cannot deploy before the scan passes. |
| Matrix: live | Retain its seven datasets; move to release | Seven agent/RAG contracts run serially against the newly deployed release. They are required rather than manually selected advisory jobs. |
| Promptfoo — live security | Retain; move to release | Two repeated provider/grader trials use real model calls against checked-out release source and governed local corpora. Failure blocks release acceptance. |
| Live fairness harness | Add to release | All 19 authored pairs run once: 19 pair comparisons / 38 coaching requests, with independent correctness, parity, identity, usage and cleanup checks. |

Ordinary CI has no paid-live checkbox or live matrix. Its report labels live
acceptance **PENDING — required after deployment in Release to AWS**. A successful
CI check precedes release and does not prove that deployed acceptance passed.
Documentation-only/no-op releases have no new deployment to evaluate. Historical
CI runs retain their original optional/skipped/advisory results.

## Order and acceptance

1. Successful push CI for current `main`; validate live configuration and secret
   access, then build/publish and scan release images.
2. Reject stale releases before corpus ingestion and immediately before deployment.
   Mutating and paid release-job reruns require fresh CI.
3. Ingest/audit approved corpora, capture previous task revisions, deploy the
   coherent release, run migrations and existing health/authentication/persistence/AI smoke checks.
4. Run all 19 fairness pairs once, then seven agent/RAG datasets, then live security.
   A failed execution stops subsequent paid stages; their missing evidence remains
   incomplete. The final evidence gate always runs for a selected release.
5. Retain detailed evidence and review forms even on failure. Refresh deployment
   credentials and restore attempted service updates if checks fail; wait for stability.

Each stage is a separate job in [release.yml](../.github/workflows/release.yml):

| Job ID | Required work |
|---|---|
| `release-gate` | Successful current-main push CI and coherent release selection |
| `live-preflight` | First-attempt release context, rates, API settings and isolated model-secret access |
| `build-images` | Immutable release images and ECR/Inspector findings gate |
| `corpus` | Freshness check and approved Bedrock corpus ingestion/governance |
| `deploy-demo` | Freshness check, runtime configuration checks, circuit breaker, previous revisions, migration and ECS updates |
| `smoke` | Required health, authentication, persistence and AI safety smoke |
| `fairness` | All 19 pairs once, with 38 coaching requests |
| `live` | Seven visible agent/RAG matrix jobs; `max-parallel: 1`, `fail-fast: true` |
| `security-live` | Full two-trial live security regressions |
| `live-acceptance` | Collect artifacts and require every prerequisite job and all objective evidence to pass |
| `rollback` | Fresh deployment credentials; restore attempted services if deployment or acceptance failed |

The workflow lock covers every job, including artifact collection and rollback.
Matrix cancellation stops queued paid work after the first failure. Missing,
failed, cancelled or skipped prerequisites fail the final gate even if files
contain passing results. A stale/no-op release skips acceptance and does not
advance the successful deployment baseline. Partial service-update failures
also select rollback, because each attempt is recorded before its ECS action.
Only task family/revision references cross job boundaries; full task definitions,
environment settings and AWS credentials remain inside their original jobs.

[`post_deploy_acceptance.py`](../infra/scripts/post_deploy_acceptance.py) requires
all seven agent reports to pass with identical test/deployed release SHA and stable
deployment evidence. Fairness requires all 19 pair results, the frozen dataset
hash, exactly one result for each pair ID with repeat 1 and 38 planned requests,
real-provider identity and complete usage. Security requires the full
two-trial case/provider matrix, current case/grader hashes, complete usage and
no budget stop. Missing reports, fixture results, subsets and wrong identities
cannot establish acceptance.

The application build identity is set from `RELEASE_SHA`, including runtime
configuration verification. The workflow event's default-branch SHA cannot
substitute for the checked-out release source.

## Required configuration and bounds

The existing `demo` environment, deployment configuration and
`SMOKE_BACKEND_API_KEY` remain required. Configure these repository or `demo`
environment variables before enabling a release with this wiring:

| Variable | Purpose |
|---|---|
| `LIVE_MODEL_INPUT_USD_PER_MILLION` | Positive finite input-token rate for the configured model/account |
| `LIVE_MODEL_OUTPUT_USD_PER_MILLION` | Positive finite output-token rate for the configured model/account |
| `FAIRNESS_LIVE_MAX_COST_USD` | Fairness estimated-cost ceiling; defaults to USD 1 |
| `AWS_INVESTMENT_TEST_ROLE_ARN` | Existing role allowed to read the evaluation model secret |
| `INVESTMENT_TEST_OPENAI_SECRET_ID` | Existing secret containing `openai-api-key` |

The security role's OIDC trust must accept the exact `demo` environment subject
`repo:OWNER/REPOSITORY:environment:demo`, rather than only the former main-ref
subject. Secret permissions remain scoped to the existing evaluation secret.
The workflow preflights role/secret access before changing services. Security
credentials are confined to the preflight/scan steps in their separate jobs using the AWS action's
[documented credential-output settings](https://github.com/aws-actions/configure-aws-credentials#retrieving-credentials-from-step-output);
they do not replace the deployment credentials used by rollback.

General agent suites retain 75,000-token bounds and one repetition; Investment
retains its 200,000-token bound. Fairness uses one repetition, a one-million
token ceiling and the configured cost ceiling. Security uses two trials with
one million conservatively reserved tokens. These are bounded samples, not an
account-credit guarantee; API turns can cross stop-before-next-request bounds.
Fairness treats exceeding its final token/cost limit as failure. Missing usage
stops further generation. Fairness, each agent/RAG matrix entry and security
have 45-minute execution timeouts inside 50-minute jobs, leaving time for evidence.
Deployment has a separate 45-minute job limit; smoke and acceptance each have
15 minutes, and rollback has 20 minutes with fresh credentials. The release lock
remains held across these jobs.

Do not lower correctness thresholds to fit an inadequate budget. A budget stop
is incomplete acceptance and rolls the release back. Change reviewed limits or
the versioned sampling policy explicitly when necessary.

## Evidence and limitations

Download **`release-live-acceptance-<run_id>`** from **Release to AWS**. It retains
the aggregate `acceptance.json`/summary, seven full agent reports, fairness JSON,
blinded `fairness-human-review.csv`, security results, scenario definitions and
hashable inputs for 90 days. Individual jobs also retain `release-fairness-<run_id>`,
`release-agent-live-<suite>` and `release-security-<run_id>` artifacts; the final
gate merges them into the aggregate artifact and initializes missing suites as
NOT RUN. CI's offline artifacts and `investment-evaluation-metrics`
retain their existing purpose and retention.

Fairness automation tests structural parity and independent expected outcomes.
The report continues to say human review is pending and overall fairness
acceptance is not established. Semantic explanation quality and representative
user validation remain separate. Promptfoo exercises real model behavior and
release source with governed local retrieval; deployed authentication, persisted
sessions and AWS retrieval are covered by the smoke/agent/fairness suites.

Rollback restores service task revisions; it does not undo additive database
migrations or corpus ingestion. Infrastructure/service-circuit-breaker controls
remain in place. Wiring and simulated tests do not establish a successful paid
run; actual acceptance is the retained release report.

## Local wiring verification

The initial 2026-10-11 full infrastructure/provider run and targeted module reruns
established 755 passing pytest cases. Five existing release-selection tests
skipped because `jq` was unavailable locally; their CI checks remain intact.
All 204 offline security trials, 12 JavaScript grader tests and 80 workflow Bash
syntax checks passed. The gate tests reject missing/duplicate/extra fairness pairs
and exercise rollback using a local AWS command stub.

The [verification record](evaluation-evidence/release-live-acceptance-wiring-2026-10-11.json)
retains source hashes, execution details and limitations. These checks made no
paid model calls or remote deployment and do not establish actual live acceptance.

The subsequent [job-split verification](evaluation-evidence/release-job-split-verification-2026-10-11.json)
covers job failure/cancellation/skip propagation, incomplete artifacts, per-job
rerun guards, partial deployment rollback and successful deployment-baseline
selection. Actionlint and Bash syntax checks validate the split workflow.
The full infrastructure/provider run with the corrected acceptance-module rerun
established 823 passing pytest cases, zero failures and the same five `jq` skips.
Actionlint 1.7.12, Ruff and all 97 CI/release Bash syntax checks passed.

The first release of this wiring, [38115829213](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38115829213),
stopped before service changes because both token-rate variables were unset.
The `demo` rates were subsequently configured to USD 0.10 input / USD 0.50 output
per million tokens for standard short-context GPT-6 Luna, checked against
[OpenAI pricing](https://developers.openai.com/api/docs/pricing) on 2026-10-11.
These rates are cost-estimation settings, not a billing guarantee. The existing
evaluation role's trust now includes the exact `demo` subject as well as its
existing main-ref subject; its secret-read permission remains scoped to the
existing evaluation secret. Configuration and local tests do not establish live
acceptance; the next release must pass all required jobs.
