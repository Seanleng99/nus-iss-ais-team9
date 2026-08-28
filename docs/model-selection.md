# Bedrock Model Selection

## Decision

Amazon Nova Lite through `apac.amazon.nova-lite-v1:0` remains the selected model for the synthetic-data demo. Amazon Nova Micro is materially cheaper, but it did not satisfy the required 100 percent dependency-behavior gate. This decision does not approve either model for real personal financial data, regulated advice, or production users.

The comparison uses prompt set `v3`, the same orchestrator and deterministic tools as the service, and the local approved Education fixture so both models receive identical retrieval evidence. Both models are invoked from `ap-southeast-1` through geography-bound APAC inference profiles. Live catalog inspection must show each profile as active, account invocation must succeed, and the deployment source Region must match the selection policy before quality measurements are eligible.

## Selection Policy

`infra/llmsecops/model-comparison-policy.json` is the machine-readable decision policy. `infra/llmsecops/model-comparison-cases.jsonl` contains 15 synthetic cases spanning routing, dynamic dependencies, safety, RAG, and paired fairness consistency. Each case is repeated three times, giving 45 structural results per model.

The hard gates are:

- active catalog entry and verified account entitlement;
- invocation from `ap-southeast-1` and APAC inference geography;
- zero provider or harness execution errors;
- 100 percent overall and category structural pass rates;
- per-request P95 no greater than 10 seconds; and
- estimated run cost no greater than USD 0.05.

An objectively eligible candidate does not replace the baseline automatically. It advances to blinded human review of explanation clarity, groundedness, uncertainty calibration, and safe helpfulness. The baseline stays selected until that review is approved through normal change control.

## Comparison Evidence

The completed AWS run on 2026-08-28 used comparison ID `nova-lite-vs-nova-micro-2026-08`. Both profiles were active, exposed six APAC destination Regions, completed all 45 cases, and produced no invocation errors.

| Metric | Nova Lite baseline | Nova Micro candidate | Gate |
|---|---:|---:|---:|
| Overall structural pass | 45/45 (100%) | 44/45 (97.78%) | 100% |
| Routing | 100% | 100% | 100% |
| Dynamic dependency | 100% | 88.89% | 100% |
| Safety | 100% | 100% | 100% |
| RAG | 100% | 100% | 100% |
| Fairness consistency | 100% | 100% | 100% |
| P50 per request | 4,437.41 ms | 3,898.24 ms | Informational |
| P95 per request | 8,151.48 ms | 8,781.05 ms | At most 10,000 ms |
| P99 per request | 8,574.00 ms | 10,242.69 ms | Informational |
| Audited input/output tokens | 86,673 / 32,358 | 67,629 / 21,894 | Informational |
| Estimated run cost | USD 0.012966 | USD 0.005432 | At most USD 0.05 |

Micro reduced estimated comparison cost by about 58 percent, but one repetition of `goal-budget-spending-chain` converted a grounded emergency-fund assessment into a global compliance block. The expected dependency chain and deterministic calculations completed, yet the final block outcome was inconsistent with the approved educational behavior. The failure is therefore a model-behavior result, not an entitlement, routing, tool, or transport error.

Because Micro failed a hard structural gate, the decision is `retain_baseline`; a subjective review is not used to override that failure. Nova Lite remains the selected synthetic-demo model.

## Reproduction And Evidence Handling

Run the comparison from GitHub Actions with **Bedrock Model Comparison** or locally with:

```powershell
python infra/scripts/model_comparison.py `
  --policy infra/llmsecops/model-comparison-policy.json `
  --output artifacts/model-comparison.json `
  --human-review-output artifacts/model-comparison-human-review.csv `
  --review-key-output artifacts/model-comparison-review-key.json
```

The workflow uses short-lived GitHub OIDC credentials and a least-privilege role limited to the two approved inference profiles and their exact APAC destination model ARNs. It uploads the JSON report, blinded review CSV, and separately keyed rubric for 90 days. The raw artifact is not committed because it contains synthetic prompts and generated answers; this document retains the aggregate decision evidence.

The report records model/profile and foundation IDs, source Region, inference geography, catalog destinations, prompt version, commit SHA, case and repeat IDs, structural checks, latency, audited tokens, price assumptions, execution errors, gate failures, and the deterministic selection reason. Recheck current [Bedrock inference-profile support](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html) and [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) before every formal run.

Rerun the comparison after changes to models, prompts, orchestration, tools, retrieval behavior, policy thresholds, or the case set. A future model change requires a fresh all-green objective run, completed blinded review, documented inference-residency approval, and a reviewed configuration change.
