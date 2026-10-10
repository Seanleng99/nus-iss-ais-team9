# Model Drift Monitoring

The detector is implemented in [model_drift.py](../infra/scripts/model_drift.py),
with independent live scoring in [drift_quality.py](../infra/scripts/drift_quality.py)
and [a weekly/manual workflow](../.github/workflows/model-drift.yml). Its policy and
12 bilingual synthetic cases are in [model-drift-policy.json](../infra/llmsecops/model-drift-policy.json)
and [model-drift-cases.jsonl](../infra/llmsecops/model-drift-cases.jsonl). It does not
ship a fabricated or automatically approved live baseline. Scheduled activation
requires a completed, independently reviewed capture and the configuration below.

## What Runs

The capture harness reuses disposable owned sessions, seeded synthetic records,
structural checks, token accounting and cleanup from `live_evaluation.py`. Before
discarding each final answer, a different configured OpenAI evaluator scores a
strict boolean contract against authored expected results, rubrics, synthetic facts
and independently checksum-verified approved source documents. Source support is
checked against the approved reference documents, not an exact replay of Bedrock's
retrieved passages. Runtime provenance checks remain separate. Provider storage and
SDK retries are disabled; input/output spend is reserved before each judge call.
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

First deploy the new provider-model and input observation metadata with the service.
Configure the `demo` GitHub environment with the existing deployment role, coach URL,
synthetic backend key and operational SNS topic, plus:

| Setting | Purpose |
|---|---|
| Secret `MODEL_DRIFT_OPENAI_API_KEY` | Evaluator credentials; never written into artifacts or command arguments. |
| Variable `MODEL_DRIFT_JUDGE_MODEL` | Explicit evaluator model supporting Responses Structured Outputs and low reasoning; it must differ from every observed generation role. |
| Variables `MODEL_DRIFT_JUDGE_INPUT_RATE`, `MODEL_DRIFT_JUDGE_OUTPUT_RATE` | Reviewed USD-per-million-token assumptions for that evaluator; both must be positive. |
| Variable `MODEL_DRIFT_JUDGE_BUDGET_USD` | Judge spending limit, default USD 0.50. |
| Variable `MODEL_DRIFT_GENERATOR_BUDGET_USD` | App generation spending limit, default USD 0.05. Raise only through a reviewed evaluation-budget change. |
| Variable `MODEL_DRIFT_ENABLED` | Set to `true` after baseline acceptance to enable Sunday 10:15 Singapore scheduled monitoring. |
| Optional variable `MODEL_DRIFT_INPUT_LOG_GROUP` | Enables aggregate input comparison for an approved log group after data/retention review. |

Apply the updated [OIDC role template](../infra/aws/github-actions-oidc.yaml) to grant
SNS publication to the existing topic and aggregate-query access to the configured
`DriftAiLogGroupName`. This source change does not establish that IAM is already
updated. Confirm the SNS subscription and exercise the new sender before claiming
notification delivery. The workflow runs only on `main` in the `demo` environment.

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
Actionable failures go to the existing SNS topic with severity, owner, metric/count/
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
current-model baseline acceptance and end-to-end SNS delivery remain deployment work.
