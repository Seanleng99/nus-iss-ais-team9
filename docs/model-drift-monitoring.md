# Model Drift Monitoring

The detector is implemented in [model_drift.py](../infra/scripts/model_drift.py),
with rubric-based live scoring in [drift_quality.py](../infra/scripts/drift_quality.py)
and [a weekly/manual workflow](../.github/workflows/model-drift.yml). Its policy and
12 bilingual synthetic cases are in [model-drift-policy.json](../infra/llmsecops/model-drift-policy.json)
and [model-drift-cases.jsonl](../infra/llmsecops/model-drift-cases.jsonl). It does not
ship a fabricated or automatically approved live baseline. Scheduled activation
requires a completed, independently reviewed capture and the configuration below.
Weekly/manual drift captures and the capture CLI default to one run of
each of the 12 cases, for 12 samples. The scored-subgroup minimum is one so the
single citation sample per language can be eligible. Smaller groups have wider
uncertainty; quality percentages, safety/financial gates, two-run regression
confirmation and independent human calibration remain required. Historical
24- and 36-sample captures below retain their original repetition counts and evidence.

## Demo Activation Status 2026-10-11

The deployed one-run configuration is published at `49843e3`, with successful
[CI](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38073037247)
and [AWS release](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38073255911).
The [12-sample candidate](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38074471495)
passed every automated gate: 12/12 structural, 6/6 financial, 2/2 citation,
10/10 groundedness and 12/12 safety, helpfulness, language and refusal scores.
Usage was complete and all 12 synthetic sessions were cleaned up. P95 was
30,571.84 ms; generation cost was USD 0.023428 and grading cost USD 0.0035016.
The user independently reviewed every answer against its facts, rubric and cited
documents and confirmed all listed criteria passed on 2026-10-11.

The approval command accepted [baseline-8608648e6e38f46b](../infra/llmsecops/model-drift-baseline.json),
with 100% human/judge agreement for every required metric. The [human review receipt](evaluation-evidence/model-drift-human-review-2026-10-11.json)
and [current activation evidence](evaluation-evidence/model-drift-activation-2026-10-11.json)
record this acceptance. The first fresh comparison passed all answer gates but
the detector incorrectly reported `configuration_changed` because three approved
roles were not invoked. Every shared role policy and all other runtime identity
fields matched. The role-coverage comparison was corrected at `5bccdfa`; replay
of that frozen capture now passes without changing its evidence or the baseline.
CI passed and no app rollout was selected.

Scheduled GitHub-only monitoring is enabled: repository and `demo` switches are
both true, with Sunday 10:15 Singapore runs. The [corrected workflow run](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38076652748)
completed all 12 samples and matched the baseline identity. It retained
`acceptance_failed` because the Chinese safety refusal received false helpfulness
and refusal-correctness flags. All 12 structural and safety checks, six financial
checks, two citation checks and ten groundedness scores passed; P95 was 36.16
seconds. The failed sample used zero model calls and the backend's deterministic
withholding message, whose baseline form was independently accepted by the user.
This indicates grading variability; it does not establish generator-model drift.
The original failed report remains an open quality alert. Enabling periodic
measurement preserves that alert and does not replace or reapprove the baseline.

The earlier [24-sample capture](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38069465972)
completed against that stable build and failed the final acceptance gate.
All 24 answers were captured with known generation/grading usage and successful
cleanup. Structural acceptance was 22/24; Risk and Compliance withheld
`budget-en:1` and `education-en:1`. No HTTP 503 or token-count failure occurred.
Citation support passed 4/4, safety and language passed 24/24, and financial
correctness passed 11/12 because the withheld Budget answer supplied no result.
P95 was 41,293.20 ms, below the 60,000 ms limit. Generation cost was USD 0.051921
and grading cost was USD 0.0067606, both within their allowances. It remains
failed historical evidence and was not used to approve the baseline.

The owned Budget trace records an initial `factual_qualification` veto and an
`unverifiable_claim` veto after one bounded claim correction. The Education trace
records `factual_qualification`, then `citation_attribution` after correction,
then `unverifiable_claim` after a separately reviewed partial answer. These are
runtime Compliance decisions, rather than citation-grader failures or transport
errors. The original intermediate drafts and correction requirements are not
retained; content-free issue locations, categories and requirement hashes cannot
establish whether each disputed claim or review was wrong. One local synthetic
diagnostic per affected case completed without withholding; neither veto was
reproduced. Those diagnostics cannot replace the original evidence or approve
this failed capture.
No veto, acceptance threshold or previous score has been overridden.

Generation and separate rubric grading both use `gpt-6-luna`, as requested.
The evaluator credential's Luna access is verified. This uses separate prompts
and contexts but does not provide different-model independence; the accepted
baseline includes independent human calibration. Reports use GitHub Actions only. Optional
email alerts and input-distribution monitoring remain disabled. The repository
and `demo` enable switches are both true; repository scope is required by the
schedule's job-level gate.

The previous [currency-fix capture](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/38065549966)
attempted all 36 samples, accounted for generation/grading usage and cleaned up
all 36 sessions. All five completed Goal answers passed currency and quality
checks. Two HTTP 503 responses left 34 answers; structural acceptance was 33/34
because Risk withheld one Spending answer for `factual_qualification`. Two
Education citation flags also failed. P95 was 37,580.74 ms, generation cost
USD 0.072292 and grading cost USD 0.0096342. This remains failed evidence.

Owned traces confirmed two router semantic-contract rejections for one 503;
the old logs did not identify the constraint. A local replay caught overlapping
reference/antecedent spans for a directly named saved goal, then its one bounded
correction succeeded. Router guidance now distinguishes direct subjects from
reference expressions. Static reason codes identify each rejected constraint;
exact, unique and nonoverlapping provenance is still required.

The other 503 happened before Risk inference when exact provider input-token
counting failed after about three seconds. Timeout is inferred from timing;
the old trace omitted the exception type. Counting now permits at most two
attempts for typed timeout/connection/server failures, within a local eight-second
budget and the remaining workflow deadline. Invalid counts and permission
failures do not retry. Generation still requires a valid exact count, and uncertain
inference spend cannot be retried. Capture execution records retain bounded
recovered error codes without prompt text or provider exception messages.

A separate held-answer diagnostic found the Chinese citations supported and
returned a contradictory English flag: false while describing the attributed
claims as supported. Grading guidance now accepts cautious faithful paraphrases
and requires a false citation flag to represent an actual unsupported/distorted
attribution. Four fixed English/Chinese positive and negative controls passed.
Original scores remain unchanged; diagnostics are not baseline evidence or human
calibration. The Spending veto was not reproduced locally and remains a failure
to investigate; its safety verdict was not overridden.

Production repairs apply to general requests without branches keyed to benchmark
case IDs, run/trace IDs or exact failing questions. They preserve owned Goal
currency, carry unsaved Spending/Budget/Goal proposals into synthesis and Risk,
and maintain backend validation, preview and separate write confirmation.
Evaluation corrections cover currency-label parsing, the Budget fixture's known-rent
arithmetic scope, citation attribution and appropriate refusal. Changed identities
require fresh capture and independent human calibration; old failures are preserved.

Current complete-answer P95 acceptance is the provisional 60,000 ms limit.
Forty-two selected earlier Luna traces had P95 51.38 seconds, motivating revision
of the inherited ten-second gate; they are not a current-build baseline. The
85-second workflow deadline remains enforced. Fixture setup, cleanup and grading
time are excluded from answer latency. Per-run allowances remain USD 0.10 for
generation and USD 0.45 for grading; missing usage stops further spending.

Historical attempts and validation are retained in [activation evidence](evaluation-evidence/model-drift-activation-2026-10-10.json),
[candidate evidence](evaluation-evidence/model-drift-candidate-2026-10-10.json)
and [repair evidence](evaluation-evidence/model-drift-repair-2026-10-10.json).
Earlier 36-sample captures keep their original three repetitions and outcomes.

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
Role metadata describes effective policies observed in model calls. A run against
the same build may omit roles that were observed in the baseline. Every currently
observed role must still match an approved baseline role exactly, including model,
provider model, reasoning effort and output limit; a new role or changed policy
requires fresh acceptance. All non-role identity fields still require exact
matching. Compatible comparisons use the baseline's approved role set for history
identity, so omitted calls do not reset consecutive regression confirmation.
Original captures and evidence hashes remain unchanged.
Missing samples, duplicate IDs, altered evidence hashes, stale history, a fixture
provider, changed policy or changed runtime/evaluator identity cannot establish a
passing comparison. The approved baseline is never reset by the monitor. The initial
policy thresholds and minimum one sample per scored subgroup are demo defaults;
review measured variation and sampling needs before accepting that policy. Wilson
intervals describe uncertainty and are not an automatic significance test.

## Capture And Approve A Baseline

The demo already has the independently accepted baseline recorded above. Use
this procedure for a fresh candidate after a configuration change; preserve the
existing baseline and failed reports until a replacement has been reviewed.

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
| Variable `MODEL_DRIFT_GENERATOR_BUDGET_USD` | App generation spending limit, default USD 0.10 for the 12-sample capture. Changes require reviewed sampling-budget configuration and fresh baseline acceptance. |
| Repository variable `MODEL_DRIFT_ENABLED` | Set to `true` after baseline acceptance to enable Sunday 10:15 Singapore scheduled monitoring. The job-level gate requires repository scope; a `demo` environment variable alone cannot enable it. |
| Optional variable `MODEL_DRIFT_EMAIL_ALERTS_ENABLED` | Default `false`; set to `true` to publish actionable failures to the existing `OPERATIONAL_ALERTS_TOPIC_ARN`. Requires updated IAM and a confirmed email subscription. |
| Optional variable `MODEL_DRIFT_INPUT_LOG_GROUP` | Enables aggregate input comparison for an approved log group after data/retention review. |

For optional AWS features, apply the updated [OIDC role template](../infra/aws/github-actions-oidc.yaml) to grant
SNS publication to the existing topic and aggregate-query access to the configured
`DriftAiLogGroupName`. This source change does not establish that IAM is already
updated. Confirm the SNS subscription and exercise the new sender before enabling
email alerts or claiming notification delivery. The workflow runs only on `main`
in the `demo` environment.
Keep the scheduling switch at repository scope: GitHub makes environment-scoped
configuration available after the runner declares the environment, while the
job-level `if` runs before that point. See [GitHub's vars context reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#vars-context).

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

### Diagnose A Failed Capture

Use the aggregate artifact's `generator_execution.records`, sample `error_code`
and CLI diagnostic lines before rerunning. Do not use failed or incomplete evidence
as a replacement baseline.
Execution records preserve bounded `error_code`/`error_codes` recovered from owned
failed traces. Router `validation_reason` and `openai.tokens.count_failed` cause
codes distinguish semantic validation, transient counting failure and permission
problems without logging generated text or SDK messages.

| Diagnostic | Response |
| --- | --- |
| `QUALITY_DEPLOYED_BUILD_CHANGED` | Finish the active deployment, discard mixed-build evidence, and recapture against one stable build. |
| `QUALITY_GENERATOR_IDENTITY_MISMATCH`, `QUALITY_ROLE_POLICY_CHANGED`, or corpus mismatch | Align deployed model/prompt/role/corpus identity with the packaged benchmark, then capture fresh evidence. |
| Fixture setup failure with an HTTP status | Fix the test record/session API failure. Known zero generation usage is retained when generation never started. |
| `MODEL_USAGE_INCONSISTENT` or other usage diagnostic | Restore complete per-call and aggregate accounting. Keep generation stopped while spend is unknown. |
| Failed structural checks or rubric flags | Inspect the private synthetic packet, reproduce the specific case, and correct app behavior or a confirmed oracle defect. Keep quality and safety thresholds unchanged during this repair. |

The workflow's completion result is insufficient for baseline acceptance: the
approval command also enforces absolute quality, subgroup coverage and independent
human calibration.

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
they do not replace the independently reviewed live baseline recorded above. End-to-end SNS delivery
verification applies only if optional email reporting is enabled.
