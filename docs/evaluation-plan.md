# Evaluation Plan

## Orchestrator Routing

Dataset: `apps/ai-service/app/evals/datasets/orchestrator_routing.jsonl`

Expected output:

- One or more selected agent names.
- Rejection reason for malicious requests.

Metrics:

- Exact-match routing accuracy.
- Multi-label precision and recall.
- Unsafe-request block rate.

Acceptance criteria:

- At least 90 percent exact-match accuracy on normal routing cases.
- 100 percent block rate for critical prompt-injection cases in the seed dataset.

## Budget Calculation

Dataset: `apps/ai-service/app/evals/datasets/budget_calculation.jsonl`

Expected output:

- Disposable income.
- Recommended allocations.
- Savings feasibility status.
- Explanation for any shortfall.

Metrics:

- Numeric tolerance within SGD 1 for deterministic calculations.
- Recommendation validity against configurable category caps.
- Explanation presence.

Acceptance criteria:

- 100 percent deterministic calculation correctness on seed cases.
- 95 percent valid budget allocations after the dataset is expanded.
- Every output includes rationale and advisory disclaimer.

## RAG Retrieval Relevance

Dataset: `apps/ai-service/app/evals/datasets/rag_retrieval.jsonl`

Expected output:

- Relevant approved source metadata attached to the Investment Education result and top-level response.
- The same sanitized education evidence supplied to Risk and Compliance for independent review.
- No use of live web content.
- Sanitized context with unsafe document instructions removed.

Metrics:

- Recall@3 for expected source IDs.
- Prompt-injection removal rate.
- Source attribution rate.

Acceptance criteria:

- Recall@3 of at least 85 percent after the knowledge base is populated.
- 100 percent explicit evidence-gap responses when no approved source passes the threshold.
- 100 percent removal of seed indirect prompt-injection instructions.
- Every Investment Education response retains controlled source metadata when RAG is used.
- Investment Education receives only `education_retriever`, not the legacy `trusted_retriever`.

## Security Controls

Dataset: `apps/ai-service/app/evals/datasets/security_guardrails.jsonl`

Expected output:

- Direct injection is blocked before agent execution.
- Sensitive identifiers are redacted.
- Embedded instructions are removed from RAG text.
- Cross-agent tool access is denied.

Metric and acceptance criterion: 100 percent security-control pass rate. Any critical failure blocks release regardless of aggregate quality.

## Dynamic Dependencies

Dataset: `apps/ai-service/app/evals/datasets/dynamic_dependencies.jsonl`

Expected output:

- The requested capability names and their centrally authorized providers.
- Correct multi-hop edges for Goal Strategy -> Budget -> Spending.
- Typed `needs_input` questions when required user facts are absent.
- No direct specialist invocation or unauthorized capability request.

Metrics:

- Exact dependency-capability match.
- Exact set of specialists requiring user input.
- Required-provider failure and cycle block rate in unit tests.

Acceptance criterion: 100 percent dependency accuracy on the seed cases. Any unauthorized edge, unresolved required dependency, or missed `needs_input` outcome fails the gate.

## Regression And Drift

`infra/llmsecops/evaluation-policy.json` stores approved metric baselines, absolute minimums, and maximum regression. Pull requests, main-branch changes, and the weekly scheduled CI run produce an evidence artifact. A metric fails when it breaches either its minimum or its permitted drop from baseline.

The fixed seed set detects behavior regression, not production input drift. After privacy approval, monitor only aggregate production distributions described in `docs/operations.md` and use observed shifts to expand representative evaluation cases.

## Model-Backed Evaluation Gate

The pull-request gate uses the explicit local fixture to test graph topology, schemas, deterministic financial calculations, retrieval, and hard security controls without AWS credentials, cost, or stochastic flakes. Passing this gate does not validate live model quality.

Before an AWS release is approved for anything beyond the synthetic demo, run the same routing cases plus representative and adversarial cases against the configured Bedrock model. Measure groundedness, unsupported-claim rate, unsafe-advice rate, explanation quality, source attribution, P50/P95 latency, token use, and cost across repeated samples. Compare the candidate with at least one lower-cost model and record model/profile IDs, prompt version, run count, and inference geography. Live-model thresholds must be stored separately from deterministic control thresholds.

## Live AWS Evaluation

`.github/workflows/aws-operational-validation.yml` runs `infra/scripts/live_evaluation.py` against the deployed backend weekly and on demand. The versioned cases in `infra/llmsecops/live-evaluation-cases.jsonl` cover routing, multi-hop dynamic dependencies, typed missing-input behavior, a critical prompt injection, and grounded Education RAG. Each case is repeated from a new synthetic session so the result measures the deployed Bedrock model, prompt set, orchestrator, backend persistence path, and Knowledge Base adapter together.

The gate requires every case-level structural check to pass. It also enforces configurable P95 latency and estimated-cost ceilings. The initial workflow ceiling is deliberately a 30-second characterization bound; after the first retained AWS run, lower `LIVE_EVAL_MAX_P95_MS` toward the eight-second demo objective using observed variance. Cost is estimated from audited input/output token counts. The default Nova Lite rates are configurable command arguments and must be checked against the current AWS pricing page before a formal assessment.

The evaluator deletes every synthetic chat session after its result is measured and treats cleanup failure as a failed case. The JSON evidence records commit SHA, target host, model/profile ID, prompt version, repeat count, category pass rate, correlation/trace IDs, check outcomes, cleanup status, source IDs, latency percentiles, token totals, and the price assumptions used. It excludes request messages, financial snapshots, answers, retrieved text, API keys, and provider payloads.

## Fairness Consistency

Create paired cases with identical financial facts and varied names, writing styles, and irrelevant profile details. Agent routing, calculations, block decisions, confidence calibration, and educational depth should remain materially equivalent. Protected attributes must not be requested or inferred for recommendation logic.

## Evidence Handling

Evaluation inputs use synthetic or approved public data. Artifacts contain metrics and case identifiers rather than raw personal prompts. Retain deterministic CI evidence for 30 days and AWS operational evidence for 90 days during development. Archive the final approved release results with the project report.
