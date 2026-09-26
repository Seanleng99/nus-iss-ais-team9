# Model Selection

## Current decision (2026-09-26)

The requested model for the synthetic-data demo is **OpenAI GPT-6 Luna** (`gpt-6-luna`) through the official Python SDK and Responses API, with `reasoning.effort=low`. The model handles model-driven routing, specialist narratives, synthesis, and independent compliance review. Deterministic calculations, pre/post-model guardrails, source allowlists, citation checks, and the separate policy review remain application controls. The runtime uses version-pinned, checksum-verified Education and Policy files packaged with the AI service rather than Amazon Bedrock Knowledge Bases.

The project uses short, role-scoped text requests and schema-validated text responses; no live audio or image input is implemented. Its per-call output cap is 1,600 tokens and run cap is 20,000 tokens, so GPT-6 Luna's 1,050,000-token context window provides headroom but is not the deciding factor. The [official model card](https://developers.openai.com/api/docs/models/gpt-6-luna) lists text and image input, text output, Structured Outputs, and USD 0.10 input / USD 0.50 output per million tokens. At the historical 45-run Nova Lite token mix (113,794 input / 32,984 output), the rate-based Luna estimate is USD 0.0279, excluding different token use, reasoning tokens, retrieval, and infrastructure. GPT-5.6 Luna would be about USD 0.0623 at that same mix, above the project's USD 0.05 comparison-run cap. [GPT-5.6 Luna rates](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

This is a configuration and implementation decision, **not a live-model acceptance result**. Luna must pass the existing routing, dependencies, safety, groundedness, Chinese-language, citation, P95 latency, and actual-cost gates on synthetic cases before deployment approval. The prompt-set-v4 Nova token counts are only an estimate basis; prompts and retrieval now differ. The deployed OpenAI API key belongs in Secrets Manager, not source control. The direct API's [Singapore data residency option offers regional storage but not regional processing](https://developers.openai.com/api/docs/guides/your-data), so the previous APAC-only Bedrock inference condition is not satisfied by this design. The project remains limited to synthetic demo data; using real personal financial information needs a fresh privacy and location review.

A local synthetic smoke check on 2026-09-26 completed one direct GPT-6 Luna request and one full Investment Education request through routing, packaged Education retrieval, synthesis, and Compliance. The latter returned two approved sources without a block. This proves basic connectivity and integration only; it does not replace the repeated acceptance suite or deployed operational evidence.

## Historical Bedrock comparison (2026-08-31)

Amazon Nova Lite through `apac.amazon.nova-lite-v1:0` was the previous selected model. The prompt-set-v4 comparison rejected Amazon Nova Micro at the objective dependency gate, so Micro did not advance to blinded human review. These results are retained as historical evidence and do not validate GPT-6 Luna.

The earlier prompt-set-v3 comparison remains historical decision evidence only. The current comparison used prompt set `v4`, the deployed orchestrator and deterministic tools, and the local approved Education fixture so both models received identical retrieval evidence. Both models were invoked from `ap-southeast-1` through geography-bound APAC inference profiles. Live catalog inspection showed each profile as active, account invocation succeeded, and the deployment source Region matched the selection policy before quality measurements were considered eligible.

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

The formal AWS run on 2026-08-31 used comparison ID `nova-lite-vs-nova-micro-v4-2026-08-31` at commit `d5e1b4a6b0f225c91ebd926f9a3a32f1060b49ed`. Both profiles were active, exposed six APAC destination Regions, completed all 45 executions, and produced no invocation errors. The retained workflow evidence is [run 33354207859](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33354207859).

| Metric | Nova Lite baseline | Nova Micro candidate | Gate |
|---|---:|---:|---:|
| Overall structural pass | 45/45 (100%) | 42/45 (93.33%) | 100% |
| Routing | 100% | 100% | 100% |
| Dynamic dependency | 100% | 66.67% | 100% |
| Safety | 100% | 100% | 100% |
| RAG | 100% | 100% | 100% |
| Fairness consistency | 100% | 100% | 100% |
| P50 per request | 4,626.03 ms | 3,981.25 ms | Informational |
| P95 per request | 7,542.90 ms | 8,022.82 ms | At most 10,000 ms |
| P99 per request | 7,855.37 ms | 8,624.78 ms | Informational |
| Audited input/output tokens | 113,794 / 32,984 | 94,077 / 22,808 | Informational |
| Audited provider calls | 189 | 171 | Informational |
| Estimated run cost | USD 0.014744 | USD 0.006486 | At most USD 0.05 |

Micro reduced estimated comparison cost by about 56 percent and was faster at P50, but it was slower at P95 and P99. More importantly, Micro incorrectly marked the synthetic missing-income request as blocked in all three repeats, even though it correctly identified that the Budget agent needed user input. That yielded `PASS_RATE_BELOW_THRESHOLD` and `DEPENDENCY_PASS_RATE_BELOW_THRESHOLD`. The deterministic machine decision is `retain_baseline`, with `human_review_required: false`; the generated 45-row blinded file is retained for diagnosis but is not an approval gate for this failed candidate run.

## Reproduction And Evidence Handling

The retired comparison can be reproduced for historical analysis only from a separately approved Bedrock environment with:

```powershell
python infra/scripts/model_comparison.py `
  --policy infra/llmsecops/model-comparison-policy.json `
  --output artifacts/model-comparison.json `
  --human-review-output artifacts/model-comparison-human-review.csv `
  --review-key-output artifacts/model-comparison-review-key.json
```

The former workflow used short-lived GitHub OIDC credentials and a least-privilege role limited to the two approved inference profiles and their exact APAC destination model ARNs. It uploaded the JSON report, blinded review CSV, and separately keyed rubric for 90 days. The raw artifact was not committed because it contains synthetic prompts and generated answers; this document retains the aggregate decision evidence. The current workflow is an inactive historical notice and never invokes Bedrock.

The report records model/profile and foundation IDs, source Region, inference geography, catalog destinations, prompt version, commit SHA, case and repeat IDs, structural checks, latency, audited tokens, price assumptions, execution errors, gate failures, and the deterministic selection reason. Recheck current [Bedrock inference-profile support](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html) and [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) before every formal run.

For the OpenAI migration, run the live GPT-6 Luna evaluation described above rather than rerunning this retired Bedrock harness. A future model change requires fresh objective results, human review, documented processing-location approval, and a reviewed configuration change. The historical prompt-set-v3 run is [run 33177819211](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33177819211).
