# Model Selection

## Current model selection (updated 2026-10-10)

The current model selection for the synthetic-data demo is **OpenAI GPT-6 Luna** (`gpt-6-luna`) through the official Python SDK and Responses API, with medium reasoning for Budget, Goal, Spending, Education and Compliance, and low reasoning for routing, planning and composition. The model handles model-driven routing, specialist narratives, synthesis, and independent compliance review. This selection is implemented in the [service defaults](../apps/ai-service/app/core/config.py), [role policy](../apps/ai-service/app/core/model-role-policy.json), and [release configuration](../.github/workflows/release.yml). Deterministic calculations, pre/post-model guardrails, source allowlists, citation checks, and the separate policy review remain application controls. Education and Policy retrieval use separate Bedrock Knowledge Bases with approved corpus pins; retrieved passages are supplied to the direct OpenAI API. Bedrock's embedding model remains independent of generation.

The project uses short, role-scoped text requests and schema-validated text responses; no live audio or image input is implemented. The packaged [current prompt contract](current-prompt-contract.md) is v10. Its aggregate request ceiling is 80,000 tokens; output limits are 3,200 for Budget/Goal/Spending, 4,000 for Education and 3,000 for Compliance. The remaining role policies are defined in `apps/ai-service/app/core/model-role-policy.json`, so GPT-6 Luna's 1,050,000-token context window provides headroom but is not the deciding factor.

## Why GPT-6 Luna is chosen

The selection prioritizes controllable reasoning and structured responses at a cost suited to repeated synthetic-demo requests. It is an engineering choice based on the workload, documented capabilities, price assumptions and implemented integration.

- **Fit for scoped agent work.** Routing, dependency planning and specialist explanations each have bounded inputs and explicit contracts. Deterministic tools calculate financial amounts, while governed retrieval supplies Education and Policy evidence. This design fits OpenAI's guidance to consider Luna for scoped tasks and to evaluate the lightest setting that meets the quality bar. [Official model-selection guidance](https://developers.openai.com/api/docs/guides/model-selection), checked on 2026-10-10.
- **Structured responses and reasoning controls.** The model supports Structured Outputs and low/medium reasoning through the Responses API. The [gateway](../apps/ai-service/app/models/gateway.py) uses these capabilities for schema-constrained agent results; application checks still validate calculations, dependencies, citations and safety. [Official GPT-6 Luna model card](https://developers.openai.com/api/docs/models/gpt-6-luna), checked on 2026-10-10.
- **A bounded quality, latency and cost tradeoff.** The [role policy](../apps/ai-service/app/core/model-role-policy.json) gives specialist writers and final Compliance review medium reasoning, and routing, planning and composition low reasoning, with output limits for each role. This allocates more reasoning to explanations and review while limiting work in frequent coordination calls. These settings are configured defaults; lower end-to-end latency and better quality still require live measurement.
- **Budget headroom within the OpenAI alternatives considered.** Standard input/output rates are USD 0.10 / USD 0.50 per million tokens, versus GPT-5.6 Luna's USD 0.20 / USD 1.20. The common-token estimate below puts GPT-6 Luna within the USD 0.05 comparison-run cap and GPT-5.6 Luna above it. This supports the cost rationale without establishing actual run cost. [OpenAI pricing](https://developers.openai.com/api/docs/pricing) and [GPT-5.6 Luna model card](https://developers.openai.com/api/docs/models/gpt-5.6-luna), checked on 2026-10-10.

The table uses the same historical Nova Lite token mix for every estimate: 113,794 input and 32,984 output tokens across 45 structural runs. Estimated cost is `(input tokens × input rate + output tokens × output rate) / 1,000,000`, with no caching discount. OpenAI rates were checked on 2026-10-10; Nova rates are the historical 2026-08-31 assumptions in the [retained comparison policy](../infra/llmsecops/model-comparison-policy.json).

| Model | Input / output USD per million tokens | Illustrative cost at common token mix | Selection status and evidence |
|---|---:|---:|---|
| **GPT-6 Luna (`gpt-6-luna`)** | 0.10 / 0.50 | **USD 0.0279** | Current configured selection; full current acceptance remains outstanding. |
| GPT-5.6 Luna (`gpt-5.6-luna`) | 0.20 / 1.20 | USD 0.0623 | Alternative considered on cost; estimate exceeds the cap; no current head-to-head result. |
| Amazon Nova Lite | 0.06 / 0.24 (historical) | USD 0.0147 | Previous Bedrock baseline; passed 45/45 in the historical v4 comparison. |
| Amazon Nova Micro | 0.035 / 0.14 (historical) | USD 0.0086 | Rejected in the historical v4 comparison after failing all three missing-income dependency repeats. |

Nova's historical rates are lower, so cost alone does not justify choosing Luna over Nova Lite. Luna is selected for the current Responses API integration, structured-output contracts and role-specific reasoning controls. No retained comparison establishes a Luna quality or latency win over Nova. The common-token estimates exclude changes in tokenization, current prompts, retrieval context, additional reasoning output, retries, retrieval fees and infrastructure. The measured Nova runs below use each model's own observed token totals, which explains Micro's different recorded cost.

## Acceptance status and limitations

This is a configuration and implementation decision, **not a live-model acceptance result**. Luna must pass the existing routing, dependencies, safety, groundedness, Chinese-language, citation, P95 latency, and cost gates on the current synthetic cases before broader deployment acceptance is claimed. The prompt-set-v4 Nova token counts are only an estimate basis; prompts and retrieval now differ. The deployed OpenAI API key belongs in Secrets Manager, not source control. The direct API's [Singapore data residency option offers regional storage but not regional processing](https://developers.openai.com/api/docs/guides/your-data), checked on 2026-10-10, so the previous APAC-only Bedrock inference condition is not satisfied by this design. The project remains limited to synthetic demo data; using real personal financial information needs a fresh privacy and location review.

A local synthetic smoke check on 2026-09-26 completed one direct GPT-6 Luna request and one full Investment Education request through routing, packaged Education retrieval, synthesis, and Compliance. The latter returned two approved sources without a block. This proves basic connectivity and integration only; it does not replace the repeated acceptance suite or deployed operational evidence.

## Historical Bedrock comparison (2026-08-31)

Amazon Nova Lite through `apac.amazon.nova-lite-v1:0` was the previous selected model. The prompt-set-v4 comparison rejected Amazon Nova Micro at the objective dependency gate, so Micro did not advance to blinded human review. These results are retained as historical evidence and do not validate GPT-6 Luna.

The earlier prompt-set-v3 comparison remains historical decision evidence only. The recorded 2026-08-31 comparison used prompt set `v4`, the deployed orchestrator and deterministic tools, and the local approved Education fixture so both models received identical retrieval evidence. Both models were invoked from `ap-southeast-1` through geography-bound APAC inference profiles. Live catalog inspection showed each profile as active, account invocation succeeded, and the deployment source Region matched the selection policy before quality measurements were considered eligible.

## Historical Bedrock Selection Policy

`infra/llmsecops/model-comparison-policy.json` retains the Bedrock candidate configuration; it does not select the current module model. The current OpenAI selection is defined by the service and release configuration above. `infra/llmsecops/model-comparison-cases.jsonl` contains 15 synthetic cases spanning routing, dynamic dependencies, safety, RAG, and paired fairness consistency. Each case is repeated three times, giving 45 structural results per model.

The historical Bedrock hard gates were:

- active catalog entry and verified account entitlement;
- invocation from `ap-southeast-1` and APAC inference geography;
- zero provider or harness execution errors;
- 100 percent overall and category structural pass rates;
- per-request P95 no greater than 10 seconds; and
- estimated run cost no greater than USD 0.05.

An objectively eligible candidate did not replace the baseline automatically. It advanced to blinded human review of explanation clarity, groundedness, uncertainty calibration, and safe helpfulness. That comparison retained Nova Lite. Any future replacement of the current `gpt-6-luna` selection requires fresh provider-specific availability and processing-location checks, repeated objective evaluation on the current prompt/retrieval contract, blinded human review, and a reviewed configuration change.

## Historical Comparison Evidence

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

The retired comparison can be reproduced for historical analysis only by checking out its recorded commit and using a separately approved Bedrock environment with:

```powershell
python infra/scripts/model_comparison.py `
  --policy infra/llmsecops/model-comparison-policy.json `
  --output artifacts/model-comparison.json `
  --human-review-output artifacts/model-comparison-human-review.csv `
  --review-key-output artifacts/model-comparison-review-key.json
```

The former workflow used short-lived GitHub OIDC credentials and a least-privilege role limited to the two approved inference profiles and their exact APAC destination model ARNs. It uploaded the JSON report, blinded review CSV, and separately keyed rubric for 90 days. The raw artifact was not committed because it contains synthetic prompts and generated answers; this document retains the aggregate decision evidence. The historical-notice workflow has been removed. Historical comparison scripts and evidence remain available for separately approved reproduction.

The report records model/profile and foundation IDs, source Region, inference geography, catalog destinations, prompt version, commit SHA, case and repeat IDs, structural checks, latency, audited tokens, price assumptions, execution errors, gate failures, and the deterministic selection reason. The retained harness policy now asserts the current packaged prompt version; running it from the current checkout would not reproduce the recorded v4 results. Recheck current [Bedrock inference-profile support](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html) and [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) before every formal run.

For current module acceptance, use the live GPT-6 Luna evaluation in the [evaluation plan](evaluation-plan.md#live-aws-evaluation). The retained comparison harness invokes Bedrock and does not compare OpenAI models. A future model change requires fresh objective results, human review, documented processing-location approval, and a reviewed configuration change. The historical prompt-set-v3 run is [run 33177819211](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33177819211).
