# Bedrock Model Selection

## Decision

Amazon Nova Lite through `apac.amazon.nova-lite-v1:0` remains the selected model for the synthetic-data demo while Amazon Nova Micro awaits blinded human review. The formal comparison made both models objectively eligible; it did not authorize an automatic replacement. This decision does not approve either model for real personal financial data, regulated advice, or production users.

The recorded comparison used prompt set `v3`, the then-current orchestrator and deterministic tools, and the local approved Education fixture so both models received identical retrieval evidence. It remains historical decision evidence. The active service now uses prompt set `v4` and conditional Education tool dependencies, so the comparison must be rerun before any model replacement decision. Both models are invoked from `ap-southeast-1` through geography-bound APAC inference profiles. Live catalog inspection must show each profile as active, account invocation must succeed, and the deployment source Region must match the selection policy before quality measurements are eligible.

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

The formal AWS run on 2026-08-28 used comparison ID `nova-lite-vs-nova-micro-2026-08` at commit `9826c8cc06225affef541e8b8c1e02531756991b`. Both profiles were active, exposed six APAC destination Regions, completed all 45 cases, and produced no invocation errors. The retained workflow evidence is [run 33177819211](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33177819211).

| Metric | Nova Lite baseline | Nova Micro candidate | Gate |
|---|---:|---:|---:|
| Overall structural pass | 45/45 (100%) | 45/45 (100%) | 100% |
| Routing | 100% | 100% | 100% |
| Dynamic dependency | 100% | 100% | 100% |
| Safety | 100% | 100% | 100% |
| RAG | 100% | 100% | 100% |
| Fairness consistency | 100% | 100% | 100% |
| P50 per request | 4,539.44 ms | 3,932.32 ms | Informational |
| P95 per request | 7,689.87 ms | 7,077.01 ms | At most 10,000 ms |
| P99 per request | 8,388.86 ms | 8,142.21 ms | Informational |
| Audited input/output tokens | 82,831 / 30,566 | 67,536 / 21,949 | Informational |
| Audited provider calls | 187 | 171 | Informational |
| Estimated run cost | USD 0.012306 | USD 0.005437 | At most USD 0.05 |

Micro reduced estimated comparison cost by about 56 percent and was faster at P50, P95, and P99 in this run. The machine decision is `pending_human_review`: the blinded 45-row review set must now be scored for explanation clarity, groundedness, uncertainty calibration, and safe helpfulness. Nova Lite remains the selected synthetic-demo model until reviewers approve Micro and the normal configuration change is reviewed and deployed.

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
