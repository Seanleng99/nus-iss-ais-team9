# Spending Agent evaluation and CI reports

**Current entry point:** **CI and LLMSecOps** → `spending` offline tests; **Release to AWS** → required `spending` live acceptance.
The former four suite IDs below describe retained scenario groups, now executed
inside one `spending` offline job. They are not separate workflow or CLI names.
Use [the consolidated workflow guide](agent-test-workflows.md) for the complete
job graph, live Yes/No choice and reports.


The `spending` offline job contains the following four scenario groups. The versioned
definitions are in [agent-evaluation-specs.json](../infra/llmsecops/agent-evaluation-specs.json);
the exact selection is in [agent-test-suites.json](../infra/llmsecops/agent-test-suites.json).
Each listed test file contains authored synthetic inputs and expected-output
assertions, including parameterized cases and scripted review failures. Reports
hash those files and count executed cases instead of relying on a fixed count.

## Datasets, expected outputs, metrics and acceptance

Test paths in this table are relative to `apps/ai-service/tests/`.

| Owned suite | Dataset | Expected output | Metric and acceptance |
| --- | --- | --- | --- |
| `spending-offline` | `test_spending_analyzer.py` | Correct category totals, rounded direction, percentage change, temporal patterns, anomalies and data quality; undefined percentage for prior zero; insufficient evidence for empty inputs | Scenario assertion pass rate 100%; zero failures/errors/skips |
| `spending-functional-capture` | `test_spending_capture.py` | Correct unsaved record/query draft, amounts/descriptions/date scope and save/preview intent; missing facts require clarification; unrelated requests do not resume capture | Scenario assertion pass rate 100%; no incorrect draft or intent tolerated |
| `spending-functional-coverage` | `test_spending_coverage.py` | Separate selected-month totals from prior-history coverage; preserve legitimate duplicate-looking transactions; exclude overlapping history, future records and unsupported currencies; retain sparse-data limitations | Scenario assertion pass rate 100%; every tested scope/count/amount invariant passes |
| `spending-functional-integration` | `test_spending_integration.py`, `test_risk_spending_coverage.py` | Analysis reaches component output; independent Risk review receives the same bounded evidence without personal descriptions/identifiers; a veto is respected | Scenario assertion pass rate 100%, including allowed and vetoed review outcomes |

## Scoring and acceptance

For every suite, `assertion_pass_rate = passed pytest cases / all reported cases`.
Failures, errors and skips stay in the denominator; parameterized instances count
separately. At least one case must execute, every assertion must pass, and the
accepted result requires zero failures/errors/skips. A numeric match cannot mask
incorrect date scope, currency leakage, fabricated coverage or an ignored veto.

The arithmetic oracle includes current food spending of 350 against prior 250:
the expected change is 40% and the direction is increased. Other assertions test
rounded monetary direction, prior-zero handling, statistical bounds and empty data.
These are authored regression checks, not a measured anomaly precision/recall score
or proof that a pattern generalizes to a user's future behavior.

## Execution and finding evidence

Automatic CI runs these offline jobs; Release owns required paid live acceptance. Open
its **spending — offline regression tests** job and download `agent-offline-spending`.
It contains JUnit, dataset hashes, expected outputs, metrics, acceptance criteria,
full synthetic example responses and every case outcome, retained for 90 days.
The combined `agent-evaluation-report` artifact includes HTML, JSON and Markdown.

Live integration runs automatically in **Release to AWS** after deployment
and required smoke. Every planned live contract must pass; failure or incomplete
evidence fails the release and rolls changed services back. Download
`release-live-acceptance-<run_id>` for full evidence (90 days). See
[required live release acceptance](post-deployment-acceptance.md).

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
