# Agent Design

## Current Execution Mode

The primary runtime is a non-deterministic, model-driven multi-agent workflow. LangGraph executes boundary inspection, model routing, one or more specialist agents, model synthesis, and an independent Risk and Compliance review. Amazon Bedrock Converse is the deployed model gateway, and all model temperatures are intentionally greater than zero.

The architecture is hybrid rather than unconstrained. Deterministic calculators, retrieval ranking, PII redaction, prompt-injection checks, and tool allowlists produce trusted grounding and hard policy decisions. Models choose agents and interpret that grounding, but cannot name or invoke arbitrary tools. Pydantic validates every model response before the graph advances; invalid output fails closed as a sanitized `503` response.

`MODEL_PROVIDER=local_fixture` is an explicit offline adapter for unit tests, fixed CI regression datasets, and local Compose. It is deterministic by design and configuration validation rejects it outside `local` and `test` environments. It is not the deployed agent behavior.

## Roles, Memory, And Tools

| Agent | Model-driven responsibility | Current memory | Approved tool | Explainability and safety |
|---|---|---|---|---|
| Spending | Aggregate recent transactions and describe category patterns | Request-scoped financial snapshot | `transaction_summarizer` | Uses only supplied transactions; reports arithmetic and avoids lifestyle inference |
| Budget | Produce a constrained monthly baseline | Request-scoped income and recurring expenses | `budget_calculator` | Shows disposable income, method, allocations, and missing-input uncertainty |
| Goal Strategy | Project user-defined savings goals | Request-scoped goals | `goal_projection` | Shows remaining amount, time horizon, and monthly requirement |
| Investment Education | Explain general investment concepts | Sanitized request and request-scoped constraints | None | Makes no retrieval or source-verification claims and avoids product instructions |
| Risk and Compliance | Validate requests and specialist outputs against trusted evidence | Sanitized request, agent results, and retrieved policy context | `policy_checker`, `trusted_retriever` | Returns controlled source IDs, records policy findings, and explains blocks without exposing hidden policy text |

No agent has durable or private memory in the skeleton. The backend persists synthetic profiles, transactions, monthly budgets, and goals and can assemble a request-scoped snapshot; session history and agent memory remain disabled. Before persistent memory is enabled, the team must define purpose limitation, user access, correction, deletion, encryption, retention, and cross-session isolation tests.

## Communication

The backend calls one private AI service API. Inside that service, LangGraph passes typed state between nodes and Pydantic models validate all model decisions. Specialists receive only the sanitized message and minimized grounding assigned to their role, rather than the full user record. Risk and Compliance is the sole RAG consumer; Investment Education has no retrieval permission. A2A is deferred because agents share one owner and runtime; MCP is deferred because the small tool set is governed by a local typed allowlist.

## Model Strategy

The implemented deployment adapter calls Amazon Nova Lite through the Bedrock APAC geographic inference profile, with Titan Text Embeddings V2 reserved for future retrieval. Nova Lite avoids third-party model onboarding while providing instruction following and clear explanations through IAM-integrated managed inference. Requests can be routed among the profile's APAC destination Regions. It is a demo default, not the approved production model choice.

Before activation, compare at least one lower-cost model against the candidate on:

- Routing and tool-selection accuracy.
- Unsafe-advice refusal and prompt-injection robustness.
- Explanation quality and consistency across writing styles.
- Grounded source use and hallucination rate.
- P50/P95 latency, token usage, and estimated cost.
- Availability in `ap-southeast-1` and whether inference remains in an approved geography.

Global cross-Region inference can route outside Singapore. It is acceptable only for the synthetic demo unless the privacy owner explicitly approves the data-residency posture. AWS publishes current model IDs and regional inference options in the [Amazon Bedrock model documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/models.html).

## Prompt And Model Change Control

Prompt, model, retrieval, tool, or policy changes require a pull request and regenerated evaluation evidence. A change that alters instruction meaning increments the prompt-set version. Current audit metadata includes model provider, model ID, prompt version, route rationale, trace ID, and safety findings without recording raw prompts. Add token, latency, and source-version telemetry before production approval.
