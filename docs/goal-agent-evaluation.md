# Goal Strategy Agent evaluation and CI reports

**Current entry point:** **CI and LLMSecOps** → `goal` offline tests;
**Release to AWS** → optional `goal` live acceptance when
`RUN_LIVE_AGENT_RAG=true`. Use [the consolidated workflow guide](agent-test-workflows.md)
for job selection and reports. Disabled live stages provide no acceptance evidence;
every enabled stage must pass.

The executable evaluation definition is version 4 of
[agent-evaluation-specs.json](../infra/llmsecops/agent-evaluation-specs.json).
[agent-test-suites.json](../infra/llmsecops/agent-test-suites.json) defines exact ownership.
The following inventory includes every test file currently selected by `goal`.
Authored synthetic inputs, parameterized cases and fault injections are the datasets;
each assertion supplies its expected-output oracle. Reports retain file hashes and
measured case counts. The former suffixed scenario IDs are retired CLI names.

## Datasets, expected outputs, metrics and acceptance

Test paths below are relative to `apps/ai-service/tests/`.

| Dataset | Expected output / assertion scope |
| --- | --- |
| `test_goal_capture.py` | Create/delete requests and pending follow-ups preserve goal name, target/current amounts, duration and currency as unsaved drafts; goal analysis alongside budget creation is not mistaken for a goal mutation. |
| `test_saved_budget_capacity.py` | Confirmed monthly savings of 700 remains the shared pool without another subtraction or requiring profile income. Two goals each needing 500 per month yield combined shortfall 300; unavailable confirmed plans use an explicitly labeled illustrative fallback when permitted. |
| `test_emergency_fund.py` | Emergency-fund education carries asserted dated-spending coverage and saved goal balances with separate currencies, retrieves governed general guidance when available, states a gap rather than inventing a benchmark when unavailable, and refuses account execution. |
| `test_dynamic_dependencies.py` | Required Goal -> Budget -> Spending capabilities are authorized, scheduled, reused and resumed with their asserted feasibility or typed missing-input outcome. Independent ready work overlaps; unauthorized edges, cycles, wrong providers and required timeouts fail closed, while optional failures retain qualified results. |
| `test_conditional_financial_dependencies.py` | Saved-goal arithmetic needs no income/Budget dependency; affordability uses required monthly savings capacity and the shared pool. Explicit spending-informed feasibility retains the authorized chain, providers are reused, and an independent spending question does not manufacture a financial dependency. |
| `test_goal_education_recovery.py` | Goal references preserve new education intent. One eligible correction preserves financial calculations and evidence, stays within configured call/token/usage bounds, receives independent rereview, and retains the original withheld answer after failure, unknown usage or prohibited advice. |
| `test_goal_currency.py` | Goal projections and narrative checks preserve the owned currency and current arithmetic; ambiguous/wrong currencies receive one bounded correction without changing financial grounding. |
| `test_risk_goal_draft.py` | Goal proposals and their stated financial facts reach Risk review unchanged; either independent verdict is respected and an unsafe proposal stays withheld. |

The shared synthetic dataset
[`agent_offline_examples.jsonl`](../apps/ai-service/app/evals/datasets/agent_offline_examples.jsonl)
is executed only by `test_agent_evaluation_examples.py::test_example_goal`
in this suite. All other listed files run in full. Questions, authored expectations
and full fixture responses are attached to the JUnit/evaluation evidence.

## Scoring and arithmetic/dependency oracles

`assertion_pass_rate = passed cases / all reported cases`. Failed, error and skipped
instances and xpasses remain in the denominator. The suite must execute at least
one case and reach 100%, with zero failures/errors/skips/xpasses and all case
assertions passing.

Two goals each requiring 500 monthly against one confirmed pool of 700 must yield
combined monthly shortfall 300. The pool must not be subtracted twice. Saved-goal
remaining-amount/duration arithmetic can run without personal capacity, whereas an
affordability decision must obtain the required authorized savings capacity.
The tests inspect graph edges, provider reuse, typed missing-input outcomes and
concurrency independently of amounts. Optional provider failure may retain an
explicitly qualified result; required unresolved evidence must not silently pass.

Shared numeric dependency results also appear under the LLMSecOps policy job in
`investment-evaluation-metrics`. All tests in the inventory above remain selected by the `goal` suite in
**CI and LLMSecOps**.

Conditional Education retrieval follows the shared
[RAG Retrieval Relevance evaluation](investment-agent-evaluation.md#rag-retrieval-relevance),
including authorized dependencies, evidence gaps and source provenance.

## Execution and finding evidence

Automatic CI runs these offline jobs; Release owns optional paid live acceptance (required to pass when enabled). Open
its **goal — offline regression tests** job and download `agent-offline-goal`.
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
python infra/scripts/run_agent_tests.py --suite goal --junitxml artifacts/goal.xml
python infra/scripts/summarize_pytest_junit.py artifacts/goal.xml --suite goal --title "Goal Strategy offline" --output artifacts/goal-summary.md --evaluation-output artifacts/goal-evaluation.json
```

These commands run all retained scenario groups offline. Non-conversational
helper tests display N/A for question/response; synthetic example tests record
actual application output with fixture providers.

## Live acceptance and limitations

Release smoke checks exercise real Goal arithmetic, model calls and persisted
traces. Optional release agent/RAG stages and explicitly requested live evaluation
utilities supply further deployed dependency and behavior evidence; those suites
do not exercise a browser/UI flow. AWS Operational Validation checks infrastructure
and retention.
These fixture rates do not establish live explanation correctness, helpful goal
prioritization or calibrated uncertainty.
Independent generated-answer and representative-user review remain necessary;
reported live failures/pending reviews cannot be replaced by offline passes.
