# Budget Agent evaluation and CI reports

**Current entry point:** **CI and LLMSecOps** → `budget` offline tests;
**Release to AWS** → optional `budget` live acceptance when
`RUN_LIVE_AGENT_RAG=true`. Use [the consolidated workflow guide](agent-test-workflows.md)
for job selection and reports. Disabled live stages provide no acceptance evidence;
every enabled stage must pass.

The executable evaluation definition is version 4 of
[agent-evaluation-specs.json](../infra/llmsecops/agent-evaluation-specs.json).
[agent-test-suites.json](../infra/llmsecops/agent-test-suites.json) defines exact ownership.
The following inventory includes every test file currently selected by `budget`.
Authored synthetic inputs, parameterized cases and fault injections are the datasets;
each assertion supplies its expected-output oracle. Reports retain file hashes and
measured case counts. The former suffixed scenario IDs are retired CLI names.

## Datasets, expected outputs, metrics and acceptance

Test paths below are relative to `apps/ai-service/tests/`.

| Dataset | Expected output / assertion scope |
| --- | --- |
| `test_budget_agent.py` | SGD 5,000 income minus confirmed recurring rent of 1,500 and phone of 80 yields disposable income 3,420 and allocations 1,710 / 1,026 / 684. |
| `test_budget_planner.py` | Proposals preserve user category limits and savings targets, use the asserted historical month, report funding gaps, do not infer missing income or savings, and retain pending corrections. Expenses of 3,500 plus savings of 800 against income of 4,000 yield a 300 funding gap. |
| `test_budget_methods.py` | What-if scenarios remain separate from the base income/savings, unclassified categories require clarification, and a comparison request selects the asserted method and planning action. |
| `test_budget_capture.py` | Category/amount corrections, pending drafts, owned workspace context, currency and explicit month are preserved; unspecified values are not invented and a different month cannot borrow selected-month income. |
| `test_budget_records.py` | List/show/history and Goal capacity requests resolve the explicit period or range against saved records. Missing/ambiguous requested months remain missing rather than borrowing another plan or an illustrative profile fallback. |
| `test_budget_reasoning.py` | Writers receive scoped saved categories/commitments and separately bounded history. Conceptual questions do not require personal income; affordability still requires validated capacity. Unknown recurrence and ambiguous scope remain unavailable instead of false zero or default-plan evidence. |
| `test_budget_review.py` | Review, alternatives, follow-up and multi-month intents route to the correct read-only/confirmation path without invented categories, amounts, period or constraints; explicit language variants retain budget capture. |
| `test_edge_budget_regressions.py` | Read-only requests use the actual scoped saved records and need no unrelated income. Mutation fields are rejected; unavailable education does not invent guidance or erase the authorized financial calculation and its limitations. |
| `test_budget_missing_input.py` | Missing income requests take-home pay and only unknown commitments; supplied financial context is retained instead of repeatedly asking known fields. |

The shared synthetic dataset
[`agent_offline_examples.jsonl`](../apps/ai-service/app/evals/datasets/agent_offline_examples.jsonl)
is executed only by `test_agent_evaluation_examples.py::test_example_budget`
in this suite. All other listed files run in full. Questions, authored expectations
and full fixture responses are attached to the JUnit/evaluation evidence.

## Scoring and numeric oracles

`assertion_pass_rate = passed cases / all reported cases`, including failed,
error, skipped and xpassed cases. Every parameterized instance counts separately.
The suite must execute at least one case and achieve 100%, with zero
failures/errors/skips/xpasses.

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

Automatic CI runs these offline jobs; Release owns optional paid live acceptance (required to pass when enabled). Open
its **budget — offline regression tests** job and download `agent-offline-budget`.
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
