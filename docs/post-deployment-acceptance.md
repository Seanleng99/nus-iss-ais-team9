# Post-deployment release acceptance

**Release to AWS** requires successful current-main CI, image build/scans, governed
corpus ingestion, deployment and health/safety smoke. Live security, live fairness
and the seven-suite agent/RAG matrix are independently optional and **off by default**.
When enabled, each live stage must pass with complete evidence. A mandatory or
enabled-stage failure fails the release and restores attempted ECS service updates
to their captured previous task revisions. The workflow lock spans acceptance and rollback.

## Enabling optional live stages

Set repository variables or variables in **Settings → Environments → demo**:

| Variable | Default | Enables |
|---|---|---|
| `RUN_LIVE_SECURITY` | `false` | Full two-trial Promptfoo live security scan |
| `RUN_LIVE_FAIRNESS` | `false` | All 19 fairness pairs once: 19 comparisons / 38 coaching requests |
| `RUN_LIVE_AGENT_RAG` | `false` | All seven deployed agent/RAG suites, serially |

Use the literal value `true` to enable a stage and `false` to disable it. Unset
variables default to `false`; malformed values fail configuration validation.
Environment variables take precedence over repository variables. Set the flags
before the next successful current-main push CI starts the release. Flags are
snapshotted once by `live-preflight`; later variable edits cannot change which
stages the current release runs or requires. The choices persist until changed.

For example, enabling only `RUN_LIVE_FAIRNESS` runs smoke → fairness → final
acceptance. Enabling all three runs smoke → live security → fairness → agent/RAG
matrix → final acceptance. Leaving all three off runs smoke → final acceptance.
Required smoke still makes its existing bounded deployed-model calls.

Disabled stages are **SKIPPED — not selected**, with no passing live evidence.
An enabled stage that fails, is cancelled, skips unexpectedly or lacks complete
evidence fails the release and triggers rollback after attempted service updates.
Subsequent paid stages stop after an enabled predecessor fails. No live stage uses
`continue-on-error`; opt-in selection does not make an executed result advisory.

## Order and mandatory gates

1. Require successful push CI for current `main`; snapshot live selections and
   validate smoke configuration plus configuration for enabled live stages.
2. Build/publish immutable images and pass ECR/Inspector findings gates. Reject
   stale releases before corpus ingestion and immediately before deployment.
3. Ingest/audit approved corpora, capture previous task revisions, deploy the
   coherent release, run migrations and required health/authentication/persistence/AI smoke.
4. Run enabled stages in security → fairness → agent/RAG order, bypassing disabled
   predecessors. Matrix work remains serial (`max-parallel: 1`, `fail-fast: true`).
5. Always aggregate mandatory job conclusions and selected live evidence for an
   attempted release. Retain evidence and available review forms, then refresh
   deployment credentials and restore attempted service updates on failure.

Each stage is a separate job in [release.yml](../.github/workflows/release.yml):

| Job ID | Work and requirement |
|---|---|
| `release-gate` | Mandatory successful current-main push CI and coherent release selection |
| `live-preflight` | Mandatory first-attempt context and smoke configuration; snapshot live flags and validate selected-stage settings |
| `build-images` | Mandatory immutable images and ECR/Inspector findings gate |
| `corpus` | Mandatory freshness check and approved Bedrock ingestion/governance |
| `deploy-demo` | Mandatory runtime checks, circuit breaker, previous revisions, migration and ECS updates |
| `smoke` | Mandatory health, authentication, persistence and AI safety smoke |
| `security-live` | Optional; when enabled, full two-trial live security regressions must pass |
| `fairness` | Optional; when enabled, all 19 pairs must pass exactly once |
| `live` | Optional; when enabled, all seven agent/RAG suites must pass |
| `live-acceptance` | Mandatory final acceptance: selected-stage evidence, all mandatory job conclusions and intentional optional skips |
| `rollback` | Restore attempted services if deployment or final acceptance failed |

The final gate requires a valid preflight selection snapshot; missing or malformed
selection cannot silently disable checks. It also rejects unexpected execution of
a disabled live stage. Stale/no-op releases skip acceptance and do not advance the
successful deployment baseline. A real deployment with required smoke and final
acceptance passing can advance the baseline with optional live stages skipped.
Partial update failures select rollback because attempts are recorded before ECS
actions. Ingestion, deployment and paid-test reruns require fresh CI; rollback
can be retried separately. Only task family/revision references cross jobs; full
task definitions, secret settings and AWS credentials stay inside their jobs.

[`post_deploy_acceptance.py`](../infra/scripts/post_deploy_acceptance.py) preserves
the full evidence criteria for enabled stages: seven passing agent reports with
matching test/deployed SHA and stable deployment; all fairness pair IDs exactly
once with repeat 1, current dataset hash, real-provider identity and complete usage;
the full two-trial security matrix with current case/grader hashes and no budget
stop. Subsets, fixtures, wrong identities or incomplete enabled evidence cannot pass.
Build identity comes from the tested `RELEASE_SHA` throughout deployment and evaluation.

## Configuration and bounds

Deployment configuration and `SMOKE_BACKEND_API_KEY` remain required. Live-only
settings are validated only when their associated stage is enabled:

| Variable | Required for | Purpose |
|---|---|---|
| `LIVE_MODEL_INPUT_USD_PER_MILLION` | Fairness | Positive finite input-token estimation rate |
| `LIVE_MODEL_OUTPUT_USD_PER_MILLION` | Fairness | Positive finite output-token estimation rate |
| `FAIRNESS_LIVE_MAX_COST_USD` | Fairness | Positive estimated-cost ceiling; defaults to USD 1 |
| `AWS_INVESTMENT_TEST_ROLE_ARN` | Security | Existing isolated role allowed to read the evaluation model secret |
| `INVESTMENT_TEST_OPENAI_SECRET_ID` | Security | Existing secret containing `openai-api-key` |

When security is enabled, the role's OIDC trust must accept this repository's exact
immutable `demo` subject:
`repo:Seanleng99@73147011/nus-iss-ais-team9@1321857657:environment:demo`.
Check `gh api repos/OWNER/REPOSITORY/actions/oidc/customization/sub` for its
`sub_claim_prefix`. See [GitHub's OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).
Secret permissions remain scoped to the existing evaluation secret. Role/secret
access is preflighted before changing services only when security is enabled.
Credentials remain confined to security steps using the AWS action's
[credential outputs](https://github.com/aws-actions/configure-aws-credentials#retrieving-credentials-from-step-output).
Agent/RAG uses the existing deployment role for service inspection and retrieval.

Sampling and limits are unchanged: one repetition per agent dataset, 75,000 tokens
per general agent suite, 200,000 for Investment; all 19 fairness pairs once with
one-million-token and configured cost ceilings; two security trials with one
million conservatively reserved tokens. Missing usage stops further generation.
Budget stops are incomplete enabled-stage acceptance and trigger rollback.
Bounds are estimates rather than account-credit guarantees; final API turns can
cross stop-before-next-request limits. No correctness threshold is lowered.
Live execution has a 45-minute timeout inside each 50-minute job; deployment has
45 minutes, smoke/final acceptance 15 minutes each and rollback 20 minutes.

## CI and retained evidence

CI keeps required offline component/platform/shared contracts, security scans and
all 19 offline fairness pairs with 100% correctness and consistency. Its report
labels live suites **OPTIONAL — selected in Release to AWS; off by default**.
Container validation stays in PR/manual/scheduled CI; main releases build and scan
images once before deployment. CI has no paid-live input.

Download **`release-live-acceptance-<run_id>`** from Release for `acceptance.json`
and the final summary. The JSON records the selection snapshot, each job result,
required status and explicit skipped results. A release can pass mandatory gates
while `live_evidence_complete` is false; that does not establish live acceptance.
The artifact retains full selected-stage results, blinded fairness review forms
when fairness ran, all seven agent reports (SKIPPED when the matrix was disabled),
and frozen definitions for 90 days. Selected jobs also publish
`release-security-<run_id>`, `release-fairness-<run_id>` and
`release-agent-live-<suite>`. CI's offline artifacts retain their existing purposes.

Security uses real model calls against checked-out release source and governed
local corpora. Agent/fairness suites exercise the deployed API/AWS. Fairness
automation measures independent expected outcomes and structural parity; human
semantic/fairness review remains separately pending. Synthetic samples and
skipped stages do not establish representative-user fairness or answer quality.

Rollback restores task revisions; it does not undo additive database migrations
or corpus ingestion. Service circuit breakers remain in place. Local wiring tests
do not establish successful paid execution or a successful AWS deployment.

## Verification history

Current local verification established 866 passing infrastructure/provider pytest
cases, zero failures and five existing skips because `jq` was unavailable.
All eight selection combinations, enabled failure propagation, required smoke,
skipped report initialization and baseline compatibility passed. Actionlint
1.7.12, Ruff, all 97 CI/release Bash syntax checks and the Chinese-code inventory
check passed. These checks made no paid model calls or AWS deployment.

The earlier records below describe the mandatory-live policy that preceded this
opt-in change. The [optional-stage verification record](evaluation-evidence/optional-release-live-verification-2026-10-11.json)
records the current selection, skip, failure, rollback and baseline checks.

The initial 2026-10-11 full infrastructure/provider run and targeted module reruns
established 755 passing pytest cases. Five existing release-selection tests
skipped because `jq` was unavailable locally; their CI checks remain intact.
All 204 offline security trials, 12 JavaScript grader tests and 80 workflow Bash
syntax checks passed. The gate tests reject missing/duplicate/extra fairness pairs
and exercise rollback using a local AWS command stub.

These earlier mandatory-live wiring checks made no paid model calls or remote
deployment and do not establish actual live acceptance. Their contract snapshot
is superseded by the retained [optional-stage verification record](evaluation-evidence/optional-release-live-verification-2026-10-11.json).

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
evaluation role's trust now includes the exact immutable main and `demo` subjects
as well as its existing name-only subjects; its secret-read permission remains scoped to the
existing evaluation secret. Configuration and local tests do not establish live
acceptance; the next release must pass all required jobs.

The first split run's CI passed, but [release 38118021857](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38118021857)
stopped in OIDC preflight because the initial trust repair used name-only
subjects. No image publishing, corpus ingestion, ECS update or paid test started.
The immutable subjects above were then added and verified against the
repository's OIDC settings and numeric IDs. Existing trust and secret permissions
were preserved. When all optional stages are enabled, the order is smoke → live
security → fairness → agent/RAG matrix → final acceptance. Mandatory acceptance
and failure rollback remain required; disabled paid stages are intentionally skipped.
