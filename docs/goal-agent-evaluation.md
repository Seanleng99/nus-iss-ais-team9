# Goal Strategy Agent evaluation and CI reports

**Goal Agent Tests** owns four offline suites. Definitions are in
[agent-evaluation-specs.json](../infra/llmsecops/agent-evaluation-specs.json), with
the exact test selection in [agent-test-suites.json](../infra/llmsecops/agent-test-suites.json).
Authored test inputs cover goal drafts, targets/balances/durations, confirmed savings
pools, missing facts, dated spending, currency variants and dependency/review failures.
Assertions provide the expected-output oracle; reports retain file hashes and actual
case counts, including parameterized instances.

## Datasets, expected outputs, metrics and acceptance

Paths are relative to `apps/ai-service/tests/`.

| Owned suite | Dataset | Expected output | Metric and acceptance |
| --- | --- | --- | --- |
| `goal-offline` | `test_goal_capture.py`, `test_saved_budget_capacity.py` | Correct unsaved create/delete/follow-up draft; preserve goal amounts/currency; analysis is not mutation; confirmed shared savings pool used without double subtraction | Scenario assertion pass rate 100%; exact tested draft/amount/capacity invariants |
| `goal-functional-feasibility` | `test_emergency_fund.py` | Dated-spending coverage and separate goal balances/currencies; governed emergency-fund guidance when available; explicit evidence gap otherwise; account execution refused | Scenario assertion pass rate 100%; no invented benchmark or unsupported execution |
| `goal-functional-dependencies` | `test_dynamic_dependencies.py`, `test_conditional_financial_dependencies.py` | Saved-goal arithmetic avoids unrelated income/Budget; affordability uses authorized capacity; correct Goal -> Budget -> Spending graph, reuse/resumption and independent overlap; cycles/wrong providers/required failures rejected | Scenario assertion pass rate 100%; numeric correctness cannot hide wrong graph/permissions |
| `goal-functional-recovery` | `test_goal_education_recovery.py` | New Education intent preserved; at most one eligible correction retains calculations/evidence and independent review; configured limits respected; failure or prohibited advice retains withheld output | Scenario assertion pass rate 100%, including correction failures and usage-limit controls |

## Scoring and arithmetic/dependency oracles

`assertion_pass_rate = passed cases / all reported cases`. Failed, error and skipped
instances remain in the denominator. Every suite must execute at least one case
and reach 100%, with zero failures/errors/skips and all case assertions passing.

Two goals each requiring 500 monthly against one confirmed pool of 700 must yield
combined monthly shortfall 300. The pool must not be subtracted twice. Saved-goal
remaining-amount/duration arithmetic can run without personal capacity, whereas an
affordability decision must obtain the required authorized savings capacity.
The tests inspect graph edges, provider reuse, typed missing-input outcomes and
concurrency independently of amounts. Optional provider failure may retain an
explicitly qualified result; required unresolved evidence must not silently pass.

Shared numeric dependency results also appear under the LLMSecOps policy job in
`investment-evaluation-metrics`. These four Goal pytest suites remain owned by
**Goal Agent Tests**.

Conditional Education retrieval follows the shared
[RAG Retrieval Relevance evaluation](investment-agent-evaluation.md#rag-retrieval-relevance),
including authorized dependencies, evidence gaps and source provenance.

## Execution and finding evidence

Relevant pull requests/main pushes run all groups when AI CI or deployment is
selected. Full CI runs Monday at 10:00 Singapore time; **Goal Agent Tests** supports
manual dispatch. Docs-only changes do not trigger CI. The required agent gate
controls application build/release; see [workflow integration](agent-test-workflows.md).

Open **CI and LLMSecOps -> Goal agent tests**, or **Goal Agent Tests**:

- Each job summary records datasets/hashes, expected outputs, metric definitions,
  acceptance, actual rates and case outcomes.
- Download `goal-offline-report`, `goal-functional-feasibility-report`,
  `goal-functional-dependencies-report` and `goal-functional-recovery-report`.
- Each includes `<suite>.xml`, `<suite>-summary.md` and `<suite>-evaluation.json`,
  retained for 30 days. JSON preserves commit/selection, counts, failed/unexecuted
  IDs and acceptance. Missing definitions, empty evidence or skips fail acceptance.
- Question/response fields are available only if recorded by the scenario; an
  assertion pass is not a generated-answer quality rating.

## Local reproduction

From the repository root with shared and AI development dependencies installed:

```sh
python infra/scripts/run_agent_tests.py --suite goal-offline --junitxml artifacts/goal-offline.xml
python infra/scripts/run_agent_tests.py --suite goal-functional-feasibility --junitxml artifacts/goal-functional-feasibility.xml
python infra/scripts/run_agent_tests.py --suite goal-functional-dependencies --junitxml artifacts/goal-functional-dependencies.xml
python infra/scripts/run_agent_tests.py --suite goal-functional-recovery --junitxml artifacts/goal-functional-recovery.xml
python infra/scripts/summarize_pytest_junit.py artifacts/goal-offline.xml --suite goal-offline --title "Goal offline evaluation" --output artifacts/goal-offline-summary.md --evaluation-output artifacts/goal-offline-evaluation.json
```

Use each other suite's matching XML/output names to produce its report. No paid
model or AWS calls are made by these commands.

## Live acceptance and limitations

Release smoke checks exercise real Goal arithmetic, model calls and persisted
traces. AWS Operational Validation and browser reasoning evaluations supply
separate deployed dependency/behavior evidence. These fixture rates do not establish
live explanation correctness, helpful goal prioritization or calibrated uncertainty.
Independent generated-answer and representative-user review remain necessary;
reported live failures/pending reviews cannot be replaced by offline passes.
