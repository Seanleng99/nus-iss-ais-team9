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

`infra/llmsecops/evaluation-policy.json` stores approved metric baselines, absolute minimums, and maximum regression. Policy v4 covers routing, budgets, retrieval, guardrails, dynamic dependencies, regulated-advice behavior, and paired fairness consistency. Every case can assert multiple properties conjunctively, and every suite requires 100 percent overall case accuracy in addition to its specialist metric. Privacy-safe evidence includes failed case IDs so a green specialist metric cannot hide another failed invariant. Pull requests, main-branch changes, and the weekly scheduled CI run produce an evidence artifact. A metric fails when it breaches either its minimum or its permitted drop from baseline.

The fixed seed set detects behavior regression, not production input drift. After privacy approval, monitor only aggregate production distributions described in `docs/operations.md` and use observed shifts to expand representative evaluation cases.

## Model-Backed Evaluation Gate

The pull-request gate uses the explicit local fixture to test graph topology, schemas, deterministic financial calculations, retrieval, and hard security controls without AWS credentials, cost, or stochastic flakes. Passing this gate does not validate live model quality.

Before an AWS release is approved for anything beyond the synthetic demo, run the same routing cases plus representative and adversarial cases against the configured Bedrock model. Measure groundedness, unsupported-claim rate, unsafe-advice rate, explanation quality, source attribution, P50/P95 latency, token use, and cost across repeated samples. Compare the candidate with at least one lower-cost model and record model/profile IDs, prompt version, run count, and inference geography. Live-model thresholds must be stored separately from deterministic control thresholds.

## Live AWS Evaluation

`.github/workflows/aws-operational-validation.yml` runs `infra/scripts/live_evaluation.py` against the deployed backend weekly and on demand. The versioned cases in `infra/llmsecops/live-evaluation-cases.jsonl` cover routing, multi-hop dynamic dependencies, typed missing-input behavior, a critical prompt injection, and grounded Education RAG. Each case is repeated from a new synthetic session so the result measures the deployed Bedrock model, prompt set, orchestrator, backend persistence path, and Knowledge Base adapter together.

The expanded live set covers deterministic routing authority, independent fan-out, multi-hop scheduling, provider reuse, typed missing input, PII-redaction telemetry, critical prompt injection, regulated-advice blocking, and grounded Education RAG. The workflow repeats every case three times by default.

The gate requires every case-level structural check to pass. It also enforces a default 10-second P95 ceiling and USD 0.05 estimated-cost ceiling. The bounded load gate uses an 8-second P95 ceiling. These replace the original 30-second characterization bounds using the first retained AWS baseline while leaving limited variance above the observed live P95. Cost is estimated from audited input/output token counts. The default Nova Lite rates are configurable command arguments and must be checked against the current AWS pricing page before a formal assessment.

The evaluator deletes every synthetic chat session after its result is measured and treats cleanup failure as a failed case. The JSON evidence records commit SHA, target host, model/profile ID, prompt version, repeat count, category pass rate, correlation/trace IDs, check outcomes, cleanup status, source IDs, latency percentiles, token totals, and the price assumptions used. It excludes request messages, financial snapshots, answers, retrieved text, API keys, and provider payloads.

## Candidate Model Comparison

`.github/workflows/model-comparison.yml` runs the service orchestrator directly against the approved Nova Lite baseline and lower-cost Nova Micro candidate. `infra/llmsecops/model-comparison-policy.json` fixes model/profile IDs, source Regions, geography, checked token prices, repeats, and hard selection thresholds. The 15-case comparison set covers routing, dynamic dependencies, regulated-advice and injection safety, grounded and evidence-gap RAG, and paired fairness consistency.

Each model must have an active catalog profile, successful account entitlement, an approved Singapore source Region and APAC geography, zero execution errors, 100 percent overall/category structural accuracy, at most 10-second per-request P95, and at most USD 0.05 estimated cost. Fairness pairs execute two requests but contribute individual request latencies to the percentile distribution. A candidate that passes every objective gate advances to the generated blinded human-review rubric; it cannot change the deployed model automatically.

The 2026-08-28 three-repeat comparison retained Nova Lite. Lite passed 45/45 structural runs with 8.15-second P95 and USD 0.012966 estimated cost. Micro passed 44/45 with 8.78-second P95 and USD 0.005432 estimated cost, failing the required dependency behavior once. See `docs/model-selection.md` for the decision record and limitations.

## Fairness Consistency

Create paired cases with identical financial facts and varied names, writing styles, and irrelevant profile details. Agent routing, calculations, block decisions, confidence calibration, and educational depth should remain materially equivalent. Protected attributes must not be requested or inferred for recommendation logic.

Policy v4 contains executable pairs for budget writing style, goal-name variation, and investment-education writing style. The current structural gate compares routing, block outcomes, deterministic financial data, dependency capabilities, missing-input outcomes, source IDs, and evidence status. The candidate comparison additionally generates a blinded explanation, groundedness, uncertainty-calibration, and safe-helpfulness rubric. Human review remains a mandatory model-change gate when a candidate passes all objective checks because exact text matching is not an appropriate fairness measure for non-deterministic generation.

## Evidence Handling

Evaluation inputs use synthetic or approved public data. Artifacts contain metrics and case identifiers rather than raw personal prompts. Retain deterministic CI evidence for 30 days and AWS operational evidence for 90 days during development. Archive the final approved release results with the project report.
