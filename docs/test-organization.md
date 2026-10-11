# Offline test ownership

The CI workflow organizes offline regressions by the behavior they protect.
The seven agent/RAG matrix jobs own agent and workflow contracts. The existing
`ai-service` job is named **AI platform and shared contracts** and owns transport,
model runtime, shared libraries, lint and ownership validation.

The 11 October 2026 inventory has 2,030 AI pytest cases in 101 modules and 69
shared-library cases in six modules. Parameterized examples count separately.
This reorganization moves 53 modules / 1,250 cases out of the general job without
changing their assertions. The two scorer/report smoke tests use small synthetic
datasets; the required metrics job retains the complete frozen evaluation policy.

| Owner | AI cases at this increment | Responsibility |
|---|---:|---|
| orchestrator | 445 | Routing, task assignments, dependencies, composition/synthesis, conversation state, follow-ups, workflow deadlines and decision events |
| spending | 52 | Capture, recurring expenses, requested period and transaction analysis |
| budget | 66 | Allocation, planning methods, records and missing financial inputs |
| goal | 89 | Capture, progress, projections, currency and funding capacity |
| investment | 460 | Education intent, semantic answerability, grounding and explanation correction |
| risk-compliance | 660 | Advice/privacy/fairness boundaries, review authority, withholding and correction eligibility |
| rag | 166 | Retrieval, ranking, ingestion, governed corpora and evidence-review tooling |
| platform | 92 | HTTP/API contracts, streaming, telemetry/drift buckets, model adapters, schemas/errors and token accounting |

Shared contracts remain in `apps/shared/tests`: arithmetic/currency/period scope,
locale selection, trace protocol, review metadata and entry logging. They have
their own JUnit and acceptance report rather than being labeled language tests.
Counts are an inventory snapshot; CI always reports actual collected/executed cases.

## Source of truth and coverage

[`agent-test-suites.json`](../infra/llmsecops/agent-test-suites.json) explicitly
selects every AI and shared module. The example module has seven exact function
selectors, one per agent suite. There is no `remaining` fallback or separately
executed conversational module; conversational regressions belong to Orchestrator.
[`agent-evaluation-specs.json`](../infra/llmsecops/agent-evaluation-specs.json)
records each selected module's expected behavior and acceptance criteria.

[`check_test_ownership.py`](../infra/scripts/check_test_ownership.py) collects
actual pytest node IDs in each package and checks them against the selectors.
Unclassified cases/modules, overlapping selections, missing files/functions,
duplicate nodes and empty suites fail. Parameterized function selectors match
the exact function and all its parameter cases, not similarly named functions.
The ownership report is retained as `test-ownership.json` in `agent-offline-platform`.
Collection proves discovery/ownership; passing execution is recorded separately.

The required agent gate depends on all seven matrix results, metrics, and the
platform/shared job. Platform or shared failures, skips, cancellations or failed
ownership validation cannot satisfy a selected release gate. The platform job
also runs for a frontend-only deploy so release gating has no skipped dependency.

## Finding evidence

| GitHub Actions job | Artifact | Evidence |
|---|---|---|
| `<suite> — offline regression tests` | `agent-offline-<suite>` | JUnit, scenario definitions, expected outputs, measured outcomes and acceptance |
| AI platform and shared contracts | `agent-offline-platform` | Platform JUnit/acceptance, explicit selection and ownership inventory |
| AI platform and shared contracts | `shared-library-contracts` | Shared JUnit, scenario definitions and acceptance |
| Required evaluation metrics | `investment-evaluation-metrics` | Full 136-case/pair policy, including all 19 fairness pairs, and full-document RAG evidence |
| Combined CI and evaluation report | `agent-evaluation-report` | All seven agent results plus separate platform/shared acceptance; live evidence remains separately labeled |

The metrics artifact retains every policy dataset, including
`fairness_consistency.jsonl`, together with the policy and per-case results.

Every offline acceptance report requires an executed nonempty suite with 100%
passing cases and no failures, errors, skips or xpasses. Unit, component, API and
evaluation-contract cases may all be offline. Job names therefore say regression
tests rather than implying every case is a pure unit test. Fixture/stub evidence
does not establish live-model semantic quality or deployed acceptance.

## Running and extending the suites

From the repository root with dependencies installed:

```powershell
$env:MODEL_PROVIDER = 'local_fixture'
$env:RAG_PROVIDER = 'local_fixture'
$env:POLICY_RAG_PROVIDER = 'local_fixture'
python infra/scripts/check_test_ownership.py --output artifacts/test-ownership.json
python infra/scripts/run_agent_tests.py --suite orchestrator --junitxml artifacts/orchestrator.xml
```

Use any of the seven agent IDs, `platform`, or `shared`. Assign a new module or
function in the manifest and add its specific expectations to the catalog in the
same change. Tests that span agents have one primary behavioral owner; another
agent's involvement does not require running the same pytest case again.

Sixteen modules currently import reusable helpers from other test modules.
Ownership was changed through selectors rather than relocating those files.
Before moving files into domain folders, extract reusable helpers into support
modules or fixtures. Mixed historical incident modules can then be split by
asserted behavior while preserving every parameterized case and fixture boundary.

The scorer tests verify aggregation, report schemas, incorrect-answer rejection
and policy failures using small synthetic cases. The required metrics job owns
execution of the full versioned datasets, avoiding repeated full-policy and
fairness-dataset runs inside the Orchestrator pytest job.

Backend, frontend, infrastructure and Promptfoo provider tests retain their
package/job owners. PostgreSQL-backed service integration, deployment smoke and
paid live evaluations retain separate execution and acceptance boundaries.

Live agent/RAG, fairness and security contracts are independently optional and
off by default in the [post-deployment release gate](post-deployment-acceptance.md). CI's ownership
and offline evidence remain prerequisites to that release stage. Enabled live
stages must pass; intentional skips provide no live acceptance evidence.

## Verification of this reorganization

The [11 October 2026 local evidence](evaluation-evidence/test-organization-verification-2026-10-11.json)
records 2,098 passing AI/shared cases and one skipped Windows symlink case,
with every inventoried node reported exactly once. The RAG pytest acceptance
remains incomplete locally; CI keeps its zero-skips requirement on Ubuntu.
All 158 focused ownership/gate/report checks passed. The full policy passed
136 cases/pairs, including all 19 fairness pairs, and full-document RAG evidence
passed 100/100 cases. This is local fixture verification; it does not claim a
GitHub Actions run, live-model quality or deployed acceptance for these changes.
