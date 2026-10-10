# Investment Agent evaluation and CI reports

The **Investment Agent Tests** reusable workflow now owns the existing Investment
suites, orchestrator/routing checks, RAG unit and integration tests, and the numeric
LLMSecOps and frozen passage-retrieval gates. CI calls it for AI/deployment changes;
it can also be dispatched manually. The required agent gate fails if this workflow
fails. Moving the numeric gates out of the general AI job does not make them optional.

## Datasets, expected outputs, metrics and acceptance

The machine-readable definition is
[`agent-evaluation-specs.json`](../infra/llmsecops/agent-evaluation-specs.json).
Pytest scenarios are datasets too: their parameterized inputs and fault injections
are defined in the listed test files, and each test's assertions specify its expected
output. Reports include the hash of each dataset/test file and the measured case count
instead of a manually maintained count that can drift.

| Evaluation | Dataset | Expected output | Metric and acceptance |
| --- | --- | --- | --- |
| Orchestrator unit/component behavior | `test_orchestrator.py`, `test_education_routing_coverage.py`, `test_evaluation_runner.py` | Correct routing authority, mixed-task dispatch, safety boundary, evidence-to-compliance flow, and scoring behavior | 100% pytest assertion pass rate; zero failures/errors/skips |
| Routing accuracy | `orchestrator_routing.jsonl` | Exact selected agent set on automatic questions; explicit user selection respected separately; malicious request blocked | Exact set-match accuracy, micro precision/recall/F1, automatic-routing accuracy, override accuracy, critical block rate; policy below |
| RAG retrieval units | `test_retriever.py`, `test_local_documents.py`, `test_retrieval_boundaries.py`, `test_request_retrieval_cache.py` | Relevant approved evidence, correct metadata/ranking, privacy-safe queries, rejected weak/unapproved/injected evidence, request-scoped reuse | 100% pytest assertion pass rate; no safety failure tolerated |
| Source attribution/component relevance | `rag_retrieval.jsonl` | Required source IDs in response, correct missing-evidence and language behavior | Mean expected source recall among first three response citations >=85%; overall case accuracy and gap-case pass rate 100% |
| Actual Markdown passage relevance | Frozen `rag_evidence_v1.jsonl`, 100 cases | Required exact passages from the specified sources; correct grounded/partial/insufficient status and uncovered topics | Complete-case accuracy, passage recall and language/status slices >=99%; scope accuracy 100%; context <=1,200 words |
| RAG integration | `rag_integration.jsonl`, `test_rag_integration.py` | Authenticated `/coach` request passes through real API/orchestrator/retriever/Investment/compliance/serialization; relevant citations survive; injection/invalid metadata excluded; provider errors sanitized | 100% scenario assertion pass rate, including positive and negative cases |
| Investment safety | `test_investment_education_safety.py`, `test_investment_review_regressions.py` | Safe definitions/warnings allowed, recommendations/guarantees/account execution blocked, no unsafe text or invented citation escapes through another field | 100% scenario assertion pass rate; no aggregate score overrides a failed safety assertion |
| Beginner Investment acceptance | 30 verbatim questions in `beginner_investment_questions.jsonl`, plus dataset-integrity test | Per-row expected route/evidence/block/disclaimer properties; questions 26/27/30 refused, educational questions answerable | All 30 cases satisfy their automatic structural checks; 100% overall case accuracy and pytest assertions |
| Investment education contracts | `test_investment_education_agent.py` | Sanitized prompts, relevant retrieval, explicit evidence gaps, controlled citations, bounded correction, safe output through compliance | 100% scenario assertion pass rate |
| Hybrid answer provenance | `test_hybrid_investment_education.py` | RAG-only, mixed RAG/model and model-only sections correctly attributed; permitted fallback, numbered references and independent safety review preserved | 100% scenario assertion pass rate |

Dataset paths above are under `apps/ai-service/app/evals/datasets/`; test paths are
under `apps/ai-service/tests/`. The JSON definition gives exact repository paths.
Existing additional semantic-planner, follow-up, repair, dependency, backend and
frontend regressions still run in their existing owning jobs; this is not an inventory
of every project test.

## Routing scoring

For each labeled routing case, compare the expected and actual agent **sets**:

- Exact routing accuracy = exactly matching sets / routing cases. Agent order does
  not affect this metric. Existing complete-case contracts can still assert ordering.
- TP = correctly selected labels; FP = extra labels; FN = missing labels, summed
  across the labeled cases. Precision = TP/(TP+FP), recall = TP/(TP+FN), and F1 is
  their harmonic mean. An undefined denominator scores zero, never perfect.
- Automatic questions and `requested_agents` overrides have separate case counts,
  exact-match scores and per-case diagnostics. Overrides do not demonstrate model
  understanding. Blocking-only cases are not in routing denominators.
- Overall case accuracy remains conjunctive: correct routing cannot hide an unsafe
  answer or another failed expected invariant.

[`evaluation-policy.json`](../infra/llmsecops/evaluation-policy.json) is the executable
threshold source. It retains the existing routing minimum of 90%, but also requires
100% complete-case accuracy, 100% automatic/override accuracy, 100% precision/recall/F1
and 100% critical blocking on this small deterministic regression set. Consequently,
any seed-case regression fails. Zero regression is permitted on the new metrics.
These thresholds are regression acceptance criteria, not estimates of real user accuracy.

## What RAG relevance does and does not measure

There are two distinct metrics:

1. `source_recall_at_3` checks IDs among the first three **displayed citations** in
   the fixture orchestrator response. It is an attribution/flow contract, not raw
   Bedrock vector-search precision.
2. `passage_recall_at_3` checks authored passage requirements in actual local-document
   retrieval contexts. The pipeline can issue multiple bounded queries and merge
   results; this is not a single global list of three documents. Scope and context-size
   checks prevent retrieving a whole corpus to inflate recall. The original 100-case
   dataset and its frozen hash are unchanged. Development/holdout families and language
   labels are retained in the downloadable results.

Do not report precision@k: these datasets specify required evidence, not an exhaustive
judgment of every potentially relevant returned passage. Additional legitimate evidence
is not automatically a false positive.

Integration tests run the real application components with deterministic model output.
Local-document scenarios load the real Markdown corpus. Bedrock scenarios use the real
adapter but stub the AWS transport response; they test wiring, filters and provenance,
not AWS availability or semantic ranking. No credentials or paid calls are needed.
Live deployment/Bedrock testing remains in `aws-operational-validation.yml` and
`rag-source-governance.yml`, with separately retained results. This change does not
dispatch them or claim they passed.

## Finding the report in GitHub Actions

Open **CI and LLMSecOps -> Investment agent tests**, or a manually dispatched
**Investment Agent Tests** run:

- Each suite's job summary includes datasets/hashes, expected outputs, metric definitions,
  acceptance criteria, measured assertion pass rate and individual case outcomes.
- `investment-*-report` artifacts contain JUnit XML, Markdown and `*-evaluation.json`.
  Beginner and integration cases record the question, expected structural output and
  observed result. These are synthetic test inputs, not production conversations.
- **Routing accuracy and RAG relevance metrics** shows the numeric thresholds and
  actual scores, routing TP/FP/FN, automatic/override diagnostics, RAG slices and failed IDs.
- Download `investment-evaluation-metrics` for the Markdown summary, machine-readable
  results, policies and datasets. Evidence is retained for 30 days.
- Missing/unreadable reports, empty evaluations, failed checks or skipped cases in these
  owned pytest suites cannot be reported as an accepted result.

The beginner dataset's `answer_rubric` and `forbidden_behaviors` describe human-review
expectations. They are **not automatically scored semantic quality**. These tests do not
establish helpfulness, factual correctness of arbitrary generated explanations, live
OpenAI routing accuracy, production database persistence or 99% overall quality.

## Local reproduction

From the repository root, install `apps/shared` and `apps/ai-service[dev]`, then:

```sh
python infra/scripts/run_agent_tests.py --suite investment-orchestrator --junitxml artifacts/routing.xml
python infra/scripts/run_agent_tests.py --suite investment-rag-unit --junitxml artifacts/rag-unit.xml
python infra/scripts/run_agent_tests.py --suite investment-rag-integration --junitxml artifacts/rag-integration.xml
python -m app.evals.gate --policy infra/llmsecops/evaluation-policy.json --output artifacts/llm-evaluation-results.json
python -m app.evals.rag_evidence --dataset apps/ai-service/app/evals/datasets/rag_evidence_v1.jsonl --output artifacts/rag-evidence-results.json
python infra/scripts/summarize_investment_evaluations.py --evaluation artifacts/llm-evaluation-results.json --retrieval artifacts/rag-evidence-results.json --output artifacts/investment-evaluation-summary.md
```

Use the other four Investment suite IDs from `agent-test-suites.json` to reproduce
their pytest checks. All these commands are offline.
