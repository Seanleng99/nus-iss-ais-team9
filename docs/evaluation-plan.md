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

- Relevant source IDs attached to the Risk and Compliance result.
- No retrieved context or source claims attached to Investment Education.
- No use of live web content.
- Sanitized context with unsafe document instructions removed.

Metrics:

- Recall@3 for expected source IDs.
- Prompt-injection removal rate.
- Source attribution rate.

Acceptance criteria:

- Recall@3 of at least 85 percent after the knowledge base is populated.
- 100 percent removal of seed indirect prompt-injection instructions.
- Every Risk and Compliance review retains controlled source IDs when RAG is used.
- Investment Education never receives `trusted_retriever` permission.

## Security Controls

Dataset: `apps/ai-service/app/evals/datasets/security_guardrails.jsonl`

Expected output:

- Direct injection is blocked before agent execution.
- Sensitive identifiers are redacted.
- Embedded instructions are removed from RAG text.
- Cross-agent tool access is denied.

Metric and acceptance criterion: 100 percent security-control pass rate. Any critical failure blocks release regardless of aggregate quality.

## Regression And Drift

`infra/llmsecops/evaluation-policy.json` stores approved metric baselines, absolute minimums, and maximum regression. Pull requests, main-branch changes, and the weekly scheduled CI run produce an evidence artifact. A metric fails when it breaches either its minimum or its permitted drop from baseline.

The fixed seed set detects behavior regression, not production input drift. After privacy approval, monitor only aggregate production distributions described in `docs/operations.md` and use observed shifts to expand representative evaluation cases.

## Model-Backed Evaluation Gate

The pull-request gate uses the explicit local fixture to test graph topology, schemas, deterministic financial calculations, retrieval, and hard security controls without AWS credentials, cost, or stochastic flakes. Passing this gate does not validate live model quality.

Before an AWS release is approved for anything beyond the synthetic demo, run the same routing cases plus representative and adversarial cases against the configured Bedrock model. Measure groundedness, unsupported-claim rate, unsafe-advice rate, explanation quality, source attribution, P50/P95 latency, token use, and cost across repeated samples. Compare the candidate with at least one lower-cost model and record model/profile IDs, prompt version, run count, and inference geography. Live-model thresholds must be stored separately from deterministic control thresholds.

## Fairness Consistency

Create paired cases with identical financial facts and varied names, writing styles, and irrelevant profile details. Agent routing, calculations, block decisions, confidence calibration, and educational depth should remain materially equivalent. Protected attributes must not be requested or inferred for recommendation logic.

## Evidence Handling

Evaluation inputs use synthetic or approved public data. Artifacts contain metrics and case identifiers rather than raw personal prompts. Retain CI evidence for 30 days during development and archive the final approved release results with the project report.
