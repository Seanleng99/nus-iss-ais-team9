# Spending Agent evaluation and CI reports

**Current entry point:** **CI and LLMSecOps** → `spending` offline tests;
**Release to AWS** → optional `spending` live acceptance when
`RUN_LIVE_AGENT_RAG=true`. Use [the consolidated workflow guide](agent-test-workflows.md)
for job selection and reports. Disabled live stages provide no acceptance evidence;
every enabled stage must pass.

The executable evaluation definition is version 4 of
[agent-evaluation-specs.json](../infra/llmsecops/agent-evaluation-specs.json).
[agent-test-suites.json](../infra/llmsecops/agent-test-suites.json) defines exact ownership.
The following inventory includes every test file currently selected by `spending`.
Authored synthetic inputs, parameterized cases and fault injections are the datasets;
each assertion supplies its expected-output oracle. Reports retain file hashes and
measured case counts. The former suffixed scenario IDs are retired CLI names.

## Datasets, expected outputs, metrics and acceptance

Test paths below are relative to `apps/ai-service/tests/`.

| Dataset | Expected output / assertion scope |
| --- | --- |
| `test_spending_analyzer.py` | Synthetic current/prior category amounts and dated histories must produce asserted totals, rounded trend direction, percentage change, temporal patterns, anomaly severity and data-quality status. A zero prior amount yields no percentage; empty inputs yield insufficient evidence and empty findings. |
| `test_spending_capture.py` | Record/query statements and pending drafts preserve amount, description, date scope and save/preview intent. Missing amount/date stays missing and asks for details; analysis, budget requests and unrelated profile corrections do not create or resume transaction drafts. |
| `test_spending_coverage.py` | Selected-month totals/counts and prior-history coverage remain separate. Actual dated records reach the writer; identical legitimate expenses survive, overlapping legacy history and future records do not inflate totals, unsupported currencies are excluded, and sparse history does not establish recurring habits. |
| `test_spending_integration.py` | Scripted requests traversing Spending analysis expose the asserted trends, anomalies, temporal patterns and months/data-quality fields, including insufficient empty data. |
| `test_risk_spending_coverage.py` | Independent Risk review receives the same bounded dated coverage, category totals and currency exclusions without personal descriptions or identifiers; either review outcome is respected, including a veto. |
| `test_recurring_capture.py` | Only explicit cadence/date range can create recurrence or forecast scope; merchant names alone do not establish frequency, and read-only forecast requests do not become writes. |
| `test_spending_period_scope.py` | Requested missing-month Spending remains primary while independent Budget context stays separate; raw records are partitioned to the requested period rather than silently using another month. |

The shared synthetic dataset
[`agent_offline_examples.jsonl`](../apps/ai-service/app/evals/datasets/agent_offline_examples.jsonl)
is executed only by `test_agent_evaluation_examples.py::test_example_spending`
in this suite. All other listed files run in full. Questions, authored expectations
and full fixture responses are attached to the JUnit/evaluation evidence.

## Scoring and acceptance

For every suite, `assertion_pass_rate = passed pytest cases / all reported cases`.
Failures, errors, skips and xpasses stay in the denominator; parameterized instances
count separately. At least one case must execute, every assertion must pass, and
the accepted suite requires zero failures/errors/skips/xpasses. A numeric match cannot mask
incorrect date scope, currency leakage, fabricated coverage or an ignored veto.

The arithmetic oracle includes current food spending of 350 against prior 250:
the expected change is 40% and the direction is increased. Other assertions test
rounded monetary direction, prior-zero handling, statistical bounds and empty data.
These are authored regression checks, not a measured anomaly precision/recall score
or proof that a pattern generalizes to a user's future behavior.

## Execution and finding evidence

Automatic CI runs these offline jobs; Release owns optional paid live acceptance (required to pass when enabled). Open
its **spending — offline regression tests** job and download `agent-offline-spending`.
It contains JUnit, dataset hashes, expected outputs, metrics, acceptance criteria,
full synthetic example responses and every case outcome, retained for 90 days.
The combined `agent-evaluation-report` artifact includes HTML, JSON and Markdown.

Live integration runs in **Release to AWS** after deployment and required smoke
when `RUN_LIVE_AGENT_RAG=true` in repository or `demo` variables. It defaults off;
disabled suites are SKIPPED without live acceptance evidence. Every planned live contract must pass; failure or incomplete
evidence fails the release and rolls changed services back. Download
`release-live-acceptance-<run_id>` for full evidence (90 days). See
[post-deployment release acceptance](post-deployment-acceptance.md).

## Local reproduction

```sh
python infra/scripts/run_agent_tests.py --suite spending --junitxml artifacts/spending.xml
python infra/scripts/summarize_pytest_junit.py artifacts/spending.xml --suite spending --title "Spending offline" --output artifacts/spending-summary.md --evaluation-output artifacts/spending-evaluation.json
```

These commands run all retained scenario groups offline. Non-conversational
helper tests display N/A for question/response; synthetic example tests record
actual application output with fixture providers.

## Live acceptance and limitations

Model output and retrieval are controlled in these suites. Live release smoke checks
also exercise Spending and persisted model traces; their results remain separate
from offline regression rates. Representative generated-answer review must assess
directness, coverage limitations, supported comparisons and absence of unsupported
habit claims. These offline results do not complete that semantic or human acceptance.
