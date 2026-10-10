# Spending Agent evaluation and CI reports

**Spending Agent Tests** owns four offline evaluation suites. The versioned
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

CI calls all four suites on relevant pull requests/main pushes when AI CI or
application deployment is selected. Full scheduled CI runs Monday at 10:00 Singapore
time; individual **Spending Agent Tests** runs can be dispatched manually. Docs-only
changes do not trigger CI. See [workflow integration](agent-test-workflows.md) for
change selection and the release gate.

Open **CI and LLMSecOps -> Spending agent tests**, or **Spending Agent Tests**:

- Each job summary shows its dataset hashes, expected outputs, metric definition,
  acceptance requirements, measured rate and case outcomes.
- Download `spending-offline-report`, `spending-functional-capture-report`,
  `spending-functional-coverage-report` and `spending-functional-integration-report`.
- Each artifact contains `<suite>.xml`, `<suite>-summary.md` and
  `<suite>-evaluation.json`, retained for 30 days. JSON records the commit, exact
  selection, outcome counts, failed/unexecuted IDs and acceptance decision.
- Question/response cells are populated only when a test records those properties;
  blank cells are not real-model answers. Missing definitions, unreadable/empty
  results and skipped cases cannot produce accepted evaluation evidence.

## Local reproduction

From the repository root with `apps/shared` and `apps/ai-service[dev]` installed:

```sh
python infra/scripts/run_agent_tests.py --suite spending-offline --junitxml artifacts/spending-offline.xml
python infra/scripts/run_agent_tests.py --suite spending-functional-capture --junitxml artifacts/spending-functional-capture.xml
python infra/scripts/run_agent_tests.py --suite spending-functional-coverage --junitxml artifacts/spending-functional-coverage.xml
python infra/scripts/run_agent_tests.py --suite spending-functional-integration --junitxml artifacts/spending-functional-integration.xml
python infra/scripts/summarize_pytest_junit.py artifacts/spending-offline.xml --suite spending-offline --title "Spending offline evaluation" --output artifacts/spending-offline-summary.md --evaluation-output artifacts/spending-offline-evaluation.json
```

Repeat the reporting command with each other suite ID and its matching XML file.
All commands are offline and need no provider credentials.

## Live acceptance and limitations

Model output and retrieval are controlled in these suites. Live release smoke checks
also exercise Spending and persisted model traces; their results remain separate
from offline regression rates. Representative generated-answer review must assess
directness, coverage limitations, supported comparisons and absence of unsupported
habit claims. These four rates do not complete that semantic or human acceptance.
