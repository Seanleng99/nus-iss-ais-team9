# Budget Agent evaluation and CI reports

**Current entry point:** **CI and LLMSecOps** → `budget` offline tests; **Release to AWS** → required `budget` live acceptance.
The former four suite IDs below describe retained scenario groups, now executed
inside one `budget` offline job. They are not separate workflow or CLI names.
Use [the consolidated workflow guide](agent-test-workflows.md) for the complete
job graph, live Yes/No choice and reports.


The `budget` offline job contains the following four scenario groups. The executable
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
results are published in `investment-evaluation-metrics` from the consolidated workflow's required metrics job. Budget retains ownership of its pytest scenarios.

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

Automatic CI runs these offline jobs; Release owns required paid live acceptance. Open
its **budget — offline regression tests** job and download `agent-offline-budget`.
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
python infra/scripts/run_agent_tests.py --suite budget --junitxml artifacts/budget.xml
python infra/scripts/summarize_pytest_junit.py artifacts/budget.xml --suite budget --title "Budget offline" --output artifacts/budget-summary.md --evaluation-output artifacts/budget-evaluation.json
```

These commands run all retained scenario groups offline. Non-conversational
helper tests display N/A for question/response; synthetic example tests record
actual application output with fixture providers.

## Live acceptance and limitations

The unified Budget live job checks a real model-backed disposable-income
calculation and missing-income clarification. Its two-case synthetic sample does
not measure the whole feature set. The older nine-case Budget dataset and
multi-turn confirmation script remain available for extended validation, but
there is no separate Budget Live Acceptance workflow. Release smoke still
verifies Budget arithmetic, model execution and persisted traces. Semantic
usefulness and representative-user understanding require separate review.
