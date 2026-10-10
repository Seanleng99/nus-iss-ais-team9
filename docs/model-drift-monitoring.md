# Model Drift Monitoring

The detector is implemented in [model_drift.py](../infra/scripts/model_drift.py),
with rubric-based live scoring in [drift_quality.py](../infra/scripts/drift_quality.py)
and [a weekly/manual workflow](../.github/workflows/model-drift.yml). Its policy and
12 bilingual synthetic cases are in [model-drift-policy.json](../infra/llmsecops/model-drift-policy.json)
and [model-drift-cases.jsonl](../infra/llmsecops/model-drift-cases.jsonl). It does not
ship a fabricated or automatically approved live baseline. Scheduled activation
requires a completed, independently reviewed capture and the configuration below.

## Demo Activation Status — 2026-10-10

The latest [repair capture](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38055863270)
stopped after 11 of 36 attempts because a concurrent deployment changed the build
from `3732e89` to `50f94b5`. All attempted generation usage was accounted for;
P95 was 37,951.59 ms. This mixed-build capture is ineligible as a baseline.
It also exposed a false amount failure for the correct `2,500 SGD` format,
another withheld Spending response, and a withheld missing-input clarification.
The amount oracle now accepts the ISO currency suffix with strict numeric and
currency boundaries. The Spending lookup contract reaches both synthesis and
Compliance. Budget clarification now asks for take-home income and unknown
confirmed commitments in the requested language, without implying budget creation.
A local synthetic Luna review accepted that corrected clarification. Captures
now report a specific content-free code such as `QUALITY_DEPLOYED_BUILD_CHANGED`
instead of hiding identity failures behind a generic evidence code. Complete
deployment before recapturing; quality, safety, usage and human-calibration gates
still apply. These repairs do not authorize an automatic baseline approval.

The implementation is published on `main`, with successful [CI](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38044974592)
and [AWS release](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38045210894)
for `0c314010720baf47af537949da4ec2ad838cfe61`. The `demo` environment is
configured for GitHub Actions reports only; email alerts and input monitoring
remain disabled. Evaluator rates and spending limits are configured, and the
evaluator secret was added on 2026-10-10. The [candidate retry](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38047917395)
returned `EVALUATOR_PERMISSION_DENIED` (HTTP 403) from its harmless evaluator
preflight, before any app requests. No complete capture or accepted baseline exists.
Those failed attempts used `gpt-6-sol` only as a grader. Following the user's
instruction to use only `gpt-6-luna`, policy version 3 selects `same_model`
evaluation. Generation and grading both use Luna, with separate prompts and
contexts. This does not provide different-model independence; independent human
calibration remains mandatory. `MODEL_DRIFT_ENABLED` remains `false` until a
complete passing capture is reviewed and accepted. No
`infra/llmsecops/model-drift-baseline.json` is currently committed, so scheduled
comparison cannot pass until a reviewed baseline is created and checked in.

The project's existing credential lists only `gpt-6-luna`; a direct Structured
Outputs invocation of the selected `gpt-6-sol` evaluator returned HTTP 403.
The new GitHub secret also lacked permission for that grader call. Its Luna access
was verified by the [first Luna capture](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38048528519).
That run scored five answers and stopped when the sixth grader response could not
be verified. All six app responses passed structural checks; their observed P95
was 28,792.43 ms. The first sample failed automated helpfulness, which remains
visible in its evidence. This incomplete run cannot become a baseline. The scoring
schema now requires booleans only for applicable metrics and null for unused
metrics, with a new schema identity and more specific sanitized failure codes.
The tightened schema passed two small Luna-only connectivity checks, separate from
baseline evidence. The configured Standard rates for Luna are
USD 0.10 input / USD 0.50 output per million tokens, matching the
[official model card](https://developers.openai.com/api/docs/models/gpt-6-luna).

The [corrected-schema capture](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38049061224)
verified all six returned grader scores, but stopped before completing 36 samples
because generation usage could not be fully accounted for. Two Spending responses
were withheld by Compliance with `factual_qualification` categories, and the Budget
English sample again failed automated helpfulness. Observed P95 was 34,615.95 ms,
below the provisional latency limit; quality and completeness still failed. A
separate disposable Education diagnostic failed the approved-citation minimum,
with complete token accounting and successful cleanup. These are acceptance
failures, not confirmed relative drift: no accepted comparison baseline exists.
Resolve the live behavior and accounting failures, complete the fixed capture,
and independently calibrate it before enabling the schedule. Implementation CI
passed for the [schema correction](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38049044875).

Capture diagnostics now retain content-free per-case execution metadata: the
failure stage, bounded HTTP status/error type, usage failure codes, failed checks
and cleanup result. Fixture setup failures stop the capture with a fixture error;
because these APIs do not invoke the model, they no longer claim unknown generation
usage. Actual generation or composition usage gaps still stop further requests.
Both cost and token budgets verify per-call usage against aggregate totals.
Read-only Spending handoffs now describe a lookup rather than a proposed expense,
and Compliance receives that operation's scope without bypassing its safety review.

A three-case diagnostic on 2026-10-10 completed with verified token usage and
successful cleanup. Education returned two approved citations; English Spending
passed. Chinese Spending returned the correct SGD 300 as `300新加坡元（SGD）`,
but the amount oracle recognized only `新元`. The localized currency aliases now
include `新加坡元` and `新币`, with negative tests for wrong currencies, amounts
and numeric substrings. This diagnostic and the parser correction do not establish
a repeated, human-reviewed baseline; the earlier run's exact stop trigger remains
unconfirmed and scheduling remains disabled.
Replaying the held Chinese answer passes the corrected currency oracle. The
[repair CI](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38054470151)
passed for commit `3732e89`; the content-free
[repair evidence](evaluation-evidence/model-drift-repair-2026-10-10.json) records
the diagnostic and changes.

The Budget prompts and rubrics now consistently ask for the amount left after the
known monthly rent, with the same SGD 2500 arithmetic requirement in both languages.
They do not equate that partial calculation with complete savings capacity or
penalize an honest qualification about unknown other expenses. This changes the
dataset identity and requires a fresh capture and reviewed baseline; it does not
change any quality, safety or latency threshold.

One disposable deployed Budget case passed structural checks, matched the release
build and included provider response model IDs in all completed calls. Cleanup
succeeded. Its observed duration was 22,707.77 ms, above the inherited 10,000 ms
acceptance limit used for that historical smoke. This single observation is neither
a quality baseline nor a representative latency distribution. The content-free
[activation evidence](evaluation-evidence/model-drift-activation-2026-10-10.json)
preserves the original checks and remaining work at that time.

The current policy retains the provisional 60,000 ms P95 introduced in version 2
for complete app answers. Forty-two recorded GPT-6 Luna traces from 2026-10-09
had a median of 33.91 seconds and P95 of 51.38 seconds; 41 exceeded 10 seconds.
Those selected traces came from an earlier build and justify provisional
recalibration, not a current-build acceptance baseline. The candidate capture must
verify the limit on the deployed build. Fixture setup, cleanup and evaluator time
are excluded from measured answer latency. The app's 85-second hard workflow
deadline remains in force; time to first streamed progress is a separate target.
The versioned policy and capture identity both record the latency limit, so changing
it requires fresh baseline acceptance. Quality and safety thresholds and application
release cost gates are unchanged.
The [candidate activation evidence](evaluation-evidence/model-drift-candidate-2026-10-10.json)
records the policy correction, validation and failed candidate attempts. The
first attempt observed a structurally passing app response in 29,775.57 ms before
the evaluator failed; this is one response, not a validated latency distribution.

The configured per-run budget is reallocated from USD 0.05 generation / USD 0.50
grading to USD 0.10 generation / USD 0.45 grading, preserving the USD 0.55 combined
limit. The observed Budget response cost USD 0.002507; thirty model-backed samples
at that cost would exceed the previous generation allowance. This is a sampling
budget change, with no change to application release cost gates. Captures record
the generation allowance; a change requires fresh baseline acceptance. Missing
provider usage still stops the run and does not establish actual billed cost.

## What Runs

The capture harness reuses disposable owned sessions, seeded synthetic records,
structural checks, token accounting and cleanup from `live_evaluation.py`. Before
discarding each final answer, a separate OpenAI grading call scores a
strict boolean contract against authored expected results, rubrics, synthetic facts
and independently checksum-verified approved source documents. Source support is
checked against the approved reference documents, not an exact replay of Bedrock's
retrieved passages. Runtime provenance checks remain separate. Provider storage and
SDK retries are disabled; input/output spend is reserved before each judge call.
An evaluator preflight scores a harmless control answer before any app requests;
its usage counts toward the judge budget. Failures retain only an allowlisted code
for authentication, model access, rate limits, connectivity or invalid responses.
Missing usage, malformed scores, refusals, model changes or budget exhaustion stop
further scoring and produce incomplete evidence. Evaluator time is excluded from
the application's measured latency, and evaluator cost is reported separately.

Reports contain case/trace IDs, boolean scores, counts, Wilson intervals, model and
effective prompt identities, observed role policies, provider response model IDs,
target host, corpus versions and token/cost assumptions. They omit questions, financial facts,
answers, retrieved text, credentials and provider errors. Model self-confidence
and the app's own Compliance verdict are not independent quality scores.

Comparison checks overall, specialist, language and intent groups. Absolute quality
or operational failures block immediately; any observed unsafe answer is critical.
Ordinary relative regressions need two distinct consecutive eligible comparisons.
Missing samples, duplicate IDs, altered evidence hashes, stale history, a fixture
provider, changed policy or changed runtime/evaluator identity cannot establish a
passing comparison. The approved baseline is never reset by the monitor. The initial
policy thresholds and minimum three samples per scored subgroup are demo defaults;
review measured variation and sampling needs before accepting that policy. Wilson
intervals describe uncertainty and are not an automatic significance test.

## Establish The First Baseline

The provider-model and input-observation metadata deployment is recorded in the
2026-10-10 activation evidence above; it is no longer a deployment prerequisite.
Before a candidate capture, verify the deployed build and configure the `demo`
GitHub environment with the coach URL and synthetic backend key, plus the settings
below. GitHub-only monitoring publishes job summaries and
retained artifacts without an SNS subscription or AWS credentials. The deployment
role is used when enabling optional email alerts or input aggregate queries.

| Setting | Purpose |
|---|---|
| Secret `MODEL_DRIFT_OPENAI_API_KEY` | Evaluator credentials; never written into artifacts or command arguments. |
| Variable `MODEL_DRIFT_JUDGE_MODEL` | Explicit evaluator supporting Responses Structured Outputs and low reasoning; current policy version 3 requires `gpt-6-luna`, matching every generation role. Separate-model grading is available only with a policy change and fresh baseline acceptance. |
| Variables `MODEL_DRIFT_JUDGE_INPUT_RATE`, `MODEL_DRIFT_JUDGE_OUTPUT_RATE` | Reviewed USD-per-million-token assumptions for that evaluator; both must be positive. |
| Variable `MODEL_DRIFT_JUDGE_BUDGET_USD` | Judge spending limit, default USD 0.45. |
| Variable `MODEL_DRIFT_GENERATOR_BUDGET_USD` | App generation spending limit, default USD 0.10 for the 36-sample capture. Changes require reviewed sampling-budget configuration and fresh baseline acceptance. |
| Variable `MODEL_DRIFT_ENABLED` | Set to `true` after baseline acceptance to enable Sunday 10:15 Singapore scheduled monitoring. |
| Optional variable `MODEL_DRIFT_EMAIL_ALERTS_ENABLED` | Default `false`; set to `true` to publish actionable failures to the existing `OPERATIONAL_ALERTS_TOPIC_ARN`. Requires updated IAM and a confirmed email subscription. |
| Optional variable `MODEL_DRIFT_INPUT_LOG_GROUP` | Enables aggregate input comparison for an approved log group after data/retention review. |

For optional AWS features, apply the updated [OIDC role template](../infra/aws/github-actions-oidc.yaml) to grant
SNS publication to the existing topic and aggregate-query access to the configured
`DriftAiLogGroupName`. This source change does not establish that IAM is already
updated. Confirm the SNS subscription and exercise the new sender before enabling
email alerts or claiming notification delivery. The workflow runs only on `main`
in the `demo` environment.

Dispatch **Model Drift Monitoring** with `baseline_candidate=true`. Review the
aggregate capture artifact. A complete passing capture also produces a separate,
private synthetic Q&A packet for human calibration, retained for seven days. That
packet intentionally contains synthetic questions, facts and answers; it is not a
privacy-safe operations report and is never published through SNS. Do not use real
personal data in custom cases. Fill the packet's score fields from independent human
reviews and reduce it to a JSON array containing only `sample_id` and `scores`:

```json
[
  {
    "sample_id": "education-en:1",
    "scores": {
      "grounded": true,
      "citations_supported": true,
      "safe": true,
      "helpful": true,
      "language_correct": true,
      "refusal_correct": true
    }
  }
]
```

The example is one row only. Approval requires every captured sample, exact boolean
metric fields, no extra text/identifiers, at least 90% human/judge agreement per
metric, no critical disagreement/failure, and both human and judge absolute gates.
Human reviewers must assess the actual packet and cited source documents; copying
the automated flags is not independent calibration. Review the candidate policy's
thresholds against observed variation before approval.

```powershell
.\.venv\Scripts\python.exe -m infra.scripts.model_drift approve-baseline `
  --capture artifacts/model-quality-capture.json `
  --human-reviews artifacts/model-quality-human-reviews.json `
  --approval-reference team9-reviewed-baseline-20261010 `
  --output infra/llmsecops/model-drift-baseline.json
```

The command refuses incomplete, failed or fixture captures and refuses to overwrite
an existing baseline. The approval reference above is illustrative: use the actual
review record. Commit the reviewed aggregate baseline through the normal review
process. Model, effective prompt, deployed build, role, corpus, dataset, evaluator
or policy changes require fresh acceptance and a reviewed replacement baseline.

## Compare And Notify

For an existing capture, the comparison is reproducible without provider calls:

```powershell
.\.venv\Scripts\python.exe -m infra.scripts.model_drift compare `
  --capture artifacts/model-quality-capture.json `
  --baseline infra/llmsecops/model-drift-baseline.json `
  --previous artifacts/previous-drift.json `
  --output artifacts/model-drift.json
```

The workflow restores the latest retained comparison on `main`, including failed
runs. Matching baseline/policy/identity hashes, distinct run/evidence IDs, ordered
timestamps and a maximum 14-day gap govern confirmation; an interrupted or
ineligible run resets the streak. The workflow publishes a GitHub summary, preserves
comparison state and aggregate capture evidence for 90 days, and fails on confirmed
drift, absolute acceptance failure, incompatible configuration or incomplete evidence.
A first relative-only warning remains visible without claiming confirmed drift.
When email alerts are enabled, actionable failures go to the existing SNS topic with severity, owner, metric/count/
threshold, case IDs and the [response runbook](operational-alert-runbook.md#drift-response).
Confirmed input-only shifts are P3; quality/evidence failures are P2; safety failures
are P1. The implementation does not automatically change models or roll back.

## Optional Input Distribution Monitor

Both regular and streamed completed coaching responses emit
`coach.drift.observation` with fixed language, length, capture/analysis intent,
selected-agent, missing-input and blocked buckets plus model/prompt identity. Language
is a script heuristic, not a linguistic-quality label. These observations describe
completed requests; provider failures are monitored separately by existing error
telemetry. Composition requests do not emit an observation.

CloudWatch Logs Insights computes counts on the server; the collector never downloads
raw log messages. It filters to the current model/effective prompt/deployed build, compares seven
complete UTC days with the preceding 21 days, and verifies the log group's retention
covers both windows. This fits the existing 30-day log policy. It checks the configured
log group and matching configuration/population across each window, rejects truncated
queries, pools cells smaller than five, and requires at least 30 observations in each
window. Jensen-Shannon divergence above the policy threshold of 0.10 must persist
for two eligible runs. These are marginal bucket comparisons; live conditional
intent/language cohort comparisons are not implemented. No bucket counts or raw
values from small cells are retained in the comparison report. Inadequate samples
are incomplete evidence, not a passing population check.

Keep this optional source disabled until production-data approval and the notification
exercise are complete. A shift changes the evaluation coverage to investigate; it
does not itself establish model-quality loss. Longer reference windows require a
reviewed retention change or an approved aggregate source with sufficient history.

## Verification

`infra/scripts/tests/test_model_drift.py` and `test_drift_quality.py` exercise baseline
approval, confirmation, critical/absolute failures, malformed evidence, configuration
changes, unknown usage and spending limits, aggregate queries, notifications, and
capture-to-comparison integration with mocked endpoints. AI observation tests verify
bounded metadata and absence of content. These tests require no provider or AWS calls;
current-model baseline acceptance remains deployment work. End-to-end SNS delivery
verification applies only if optional email reporting is enabled.
