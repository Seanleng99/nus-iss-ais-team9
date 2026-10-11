# Goal Strategy Agent evaluation and CI reports

**Current entry point:** **CI and LLMSecOps** → `goal` offline tests; **Release to AWS** → required `goal` live acceptance.
The former four suite IDs below describe retained scenario groups, now executed
inside one `goal` offline job. They are not separate workflow or CLI names.
Use [the consolidated workflow guide](agent-test-workflows.md) for the complete
job graph, live Yes/No choice and reports.


The `goal` offline job contains four scenario groups. Definitions are in
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
`investment-evaluation-metrics`. These four Goal scenario groups remain selected
by the `goal` suite in **CI and LLMSecOps**.

Conditional Education retrieval follows the shared
[RAG Retrieval Relevance evaluation](investment-agent-evaluation.md#rag-retrieval-relevance),
including authorized dependencies, evidence gaps and source provenance.

## Execution and finding evidence

Automatic CI runs these offline jobs; Release owns required paid live acceptance. Open
its **goal — offline regression tests** job and download `agent-offline-goal`.
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
python infra/scripts/run_agent_tests.py --suite goal --junitxml artifacts/goal.xml
python infra/scripts/summarize_pytest_junit.py artifacts/goal.xml --suite goal --title "Goal Strategy offline" --output artifacts/goal-summary.md --evaluation-output artifacts/goal-evaluation.json
```

These commands run all retained scenario groups offline. Non-conversational
helper tests display N/A for question/response; synthetic example tests record
actual application output with fixture providers.

## Live acceptance and limitations

Release smoke checks exercise real Goal arithmetic, model calls and persisted
traces. AWS Operational Validation supplies separate deployed dependency and
behavior evidence; the consolidated live suite does not exercise a browser/UI flow.
These fixture rates do not establish live explanation correctness, helpful goal
prioritization or calibrated uncertainty.
Independent generated-answer and representative-user review remain necessary;
reported live failures/pending reviews cannot be replaced by offline passes.
