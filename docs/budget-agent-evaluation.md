# Budget Agent evaluation and CI reports

**Budget Agent Tests** owns four offline evaluation suites. The executable
definitions are in [agent-evaluation-specs.json](../infra/llmsecops/agent-evaluation-specs.json),
with selection in [agent-test-suites.json](../infra/llmsecops/agent-test-suites.json).
Test inputs cover take-home/gross/missing income, commitments, user expense and
savings amounts, methods, pending corrections and saved records by period.
Per-test assertions specify the expected output; reports retain dataset hashes and
measured counts rather than a hand-maintained scenario count.

## Datasets, expected outputs, metrics and acceptance

Test paths are relative to `apps/ai-service/tests/`.

| Owned suite | Dataset | Expected output | Metric and acceptance |
| --- | --- | --- | --- |
| `budget-offline` | `test_budget_agent.py`, `test_budget_planner.py`, `test_budget_methods.py` | Correct income after confirmed commitments, allocations and funding gaps; preserve user amounts; clarify unknown income/category classification; keep what-if changes separate | Scenario assertion pass rate 100%; all asserted amounts/rounding and planning invariants pass |
| `budget-functional-capture` | `test_budget_capture.py`, `test_budget_records.py` | Correct draft/corrections, currency and owned saved-record selection; explicit month/range respected; missing plans do not borrow another month or income | Scenario assertion pass rate 100%; zero failures/errors/skips |
| `budget-functional-reasoning` | `test_budget_reasoning.py`, `test_budget_review.py` | Scoped saved categories and separate history; conceptual questions need no personal income; personal capacity needs validated facts; review/alternatives/continuity retain their intended behavior | Scenario assertion pass rate 100%; no invented capacity, amount, period or constraint |
| `budget-functional-boundaries` | `test_edge_budget_regressions.py` | Read-only review uses actual scoped records; mutation fields rejected; unavailable conditional Education evidence leaves authorized qualified arithmetic intact | Scenario assertion pass rate 100%, including missing-evidence and rejected-mutation controls |

## Scoring and numeric oracles

`assertion_pass_rate = passed cases / all reported cases`, including failed,
error and skipped cases. Every parameterized instance counts separately. Each suite
must execute at least one case and achieve 100%, with zero failures/errors/skips.

Examples of asserted outputs:

- Income 5,000 minus confirmed rent 1,500 and phone 80 yields disposable income
  3,420, with tested baseline allocations 1,710 / 1,026 / 684.
- Income 4,000 with expenses 3,500 and requested savings 800 yields a 300 funding
  gap. The planner must preserve the requested expense/savings amounts.
- Missing/gross income or unconfirmed recurrence cannot become an invented
  available-income or zero-capacity figure.

The [Budget Calculation](#budget-calculation) JSONL seed gate
separately uses SGD 1 tolerance and 100% case/calculation acceptance. Its numeric
results are published in `investment-evaluation-metrics` because Investment's
workflow owns the shared LLMSecOps policy job. That placement does not transfer
ownership of these four Budget pytest suites.

The planned 95% expanded allocation-validity criterion is not a current measured
metric. A correct seed calculation does not establish that arbitrary real-model
recommendations satisfy user constraints or have complete explanations.

Conditional Education retrieval follows the shared
[RAG Retrieval Relevance evaluation](investment-agent-evaluation.md#rag-retrieval-relevance),
including authorized dependencies, evidence gaps and source provenance.

## Budget Calculation

Dataset: `apps/ai-service/app/evals/datasets/budget_calculation.jsonl`

Expected output:

- Disposable income.
- Recommended allocations.
- Savings feasibility status.
- Explanation for any shortfall.

Metrics:

- Numeric tolerance within SGD 1 for deterministic calculations.
- Planned expanded evaluation: recommendation validity against configurable category caps.
- Planned expanded evaluation: explanation completeness and rationale quality.

Acceptance criteria:

- 100 percent deterministic calculation correctness on seed cases.
- Planned expanded gate: 95 percent valid budget allocations after the dataset and executable scorer are expanded; this is not a current measured seed metric.
- Desired answer contract: rationale and advisory disclaimer. The four-case seed set does not independently score explanation quality or assert a disclaimer on every Budget output; use the specialist scenario assertions and separate live review described in this guide.

## Execution and finding evidence

The four suites run for relevant pull requests/main pushes when AI CI or application
deployment is selected, in full Monday 10:00 Singapore-time CI, and through manual
**Budget Agent Tests** dispatch. Docs-only changes do not trigger CI. Application
build/release requires the agent test gate; see [workflow integration](agent-test-workflows.md).

Open **CI and LLMSecOps -> Budget agent tests**, or **Budget Agent Tests**:

- Job summaries include definitions, dataset hashes, thresholds, measured rate and
  individual outcomes.
- Download `budget-offline-report`, `budget-functional-capture-report`,
  `budget-functional-reasoning-report` and `budget-functional-boundaries-report`.
- Each contains `<suite>.xml`, `<suite>-summary.md` and `<suite>-evaluation.json`,
  retained for 30 days. JSON retains commit/selection, outcome counts, failed IDs
  and acceptance. Missing/empty results or skipped cases fail acceptance.
- Questions/responses appear only when the test records them; offline output is
  not a reviewed live answer.

## Local reproduction

From the repository root with shared and AI development dependencies installed:

```sh
python infra/scripts/run_agent_tests.py --suite budget-offline --junitxml artifacts/budget-offline.xml
python infra/scripts/run_agent_tests.py --suite budget-functional-capture --junitxml artifacts/budget-functional-capture.xml
python infra/scripts/run_agent_tests.py --suite budget-functional-reasoning --junitxml artifacts/budget-functional-reasoning.xml
python infra/scripts/run_agent_tests.py --suite budget-functional-boundaries --junitxml artifacts/budget-functional-boundaries.xml
python infra/scripts/summarize_pytest_junit.py artifacts/budget-offline.xml --suite budget-offline --title "Budget offline evaluation" --output artifacts/budget-offline-summary.md --evaluation-output artifacts/budget-offline-evaluation.json
```

Use matching suite/XML/output names for the other reports. These commands are offline.

## Live acceptance and limitations

**Budget Live Acceptance** is a separate manual workflow using
`infra/llmsecops/budget-live-evaluation-cases.jsonl` and the multi-turn confirmation
harness. It checks deployed contracts and retains `budget-live-acceptance-<run_id>`
evidence for 90 days. Release smoke checks also verify Budget arithmetic, model
execution and persisted traces. Those live checks do not by themselves approve
explanation usefulness, allocation quality or representative-user understanding.
Their actual pass/fail results must remain separate from these offline rates.
