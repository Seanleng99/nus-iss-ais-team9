# Agent Design

## Current Execution Mode

The primary runtime is a non-deterministic, model-driven multi-agent workflow. LangGraph executes boundary inspection, model routing, one or more specialist agents, model synthesis, and an independent Risk and Compliance review. Amazon Bedrock Converse is the deployed model gateway, and all model temperatures are intentionally greater than zero.

The architecture is hybrid rather than unconstrained. Deterministic calculators, retrieval ranking, PII redaction, prompt-injection checks, and tool allowlists produce trusted grounding and hard policy decisions. Models choose agents and interpret that grounding, but cannot name or invoke arbitrary tools. Pydantic validates every model response before the graph advances; invalid output fails closed as a sanitized `503` response.

`MODEL_PROVIDER=local_fixture` is an explicit offline adapter for unit tests, fixed CI regression datasets, and local Compose. It is deterministic by design and configuration validation rejects it outside `local` and `test` environments. It is not the deployed agent behavior.

## Roles, Memory, And Tools

| Agent | Model-driven responsibility | Current memory | Approved tool | Explainability and safety |
|---|---|---|---|---|
| Spending | Aggregate recent transactions and publish `transaction_category_totals` | Request-scoped financial snapshot | `transaction_summarizer` | Uses only supplied transactions; reports arithmetic and avoids lifestyle inference |
| Budget | Produce a constrained monthly baseline, consume transaction totals when useful, publish `monthly_savings_capacity`, and conditionally explain investment concepts | Request-scoped income, recurring expenses, and orchestrator-resolved capabilities | `budget_calculator`; conditional `education_retriever` through the orchestrator | Preserves deterministic values; retrieves only for allowlisted investment topics; cites approved evidence or reports an evidence gap |
| Goal Strategy | Project user-defined savings goals, request savings capacity for feasibility, and conditionally explain investment concepts | Request-scoped goals plus orchestrator-resolved capabilities | `goal_projection`; conditional `education_retriever` through the orchestrator | Preserves deterministic projections; retrieves only for allowlisted investment topics; cites approved evidence or reports an evidence gap |
| Investment Education | Explain general investment concepts | Sanitized request and approved education context | `education_retriever` | Uses only approved sources, exposes citations, reports evidence gaps, and avoids product instructions |
| Risk and Compliance | Validate requests and specialist outputs against governed policy evidence | Sanitized request, specialist evidence, and approved policy context | `policy_retriever` | Uses only the separate Policy collection, sanitizes retrieved text, records policy provenance, and fails closed when current policy evidence is unavailable |

No specialist has private or self-managed durable memory. The backend persists synthetic profiles, transactions, monthly budgets, goals, chat history, and privacy-safe orchestration traces, then assembles a minimized request-scoped snapshot. Capability results live only for the current orchestration run. Policy `data-lifecycle-v1` now provides owner export/deletion, versioned future-memory consent, automatic chat/trace retention, synthetic-user expiry, and isolation tests; durable memory remains disabled until purpose-limited storage, correction, encryption review, and an explicit activation decision are implemented.

## Communication

The backend calls one private AI service API. Inside that service, LangGraph passes typed state between nodes and Pydantic models validate all model decisions. The orchestrator creates a role-scoped `AgentTask`, so Spending receives only recent transactions, Budget only income and recurring expenses, Goal Strategy only goals, and Investment Education only its sanitized question and risk constraint. Investment Education can call `education_retriever` directly. Budget and Goal Strategy can request the typed `education_context` capability only for allowlisted investment topics; the orchestrator constructs a topic-only query, invokes the retriever, caches the result within the run, and returns sanitized evidence. Compliance does not query the Education knowledge base, and Spending remains retrieval-free. Retrieved evidence is carried into synthesis and independent Compliance review. A2A is deferred because agents share one owner and runtime; MCP is deferred because the small tool set is governed by a local typed allowlist.

Specialists do not invoke one another. With prompt sets v3 and v4, an eligible specialist first returns a schema-validated dependency-planning decision: `ready`, `needs_dependency`, or `needs_input`. A dependency request names an allowlisted capability, never another agent. The orchestrator authorizes it through the deterministic registry, fingerprints the required input, reuses or schedules an agent provider, invokes an approved tool provider, records the dependency edge, rejects cycles, and resumes the requester with the minimal `CapabilityResult`. A user-input request returns typed questions without calling more specialists.

The scheduler runs independent ready tasks concurrently, while preserving dependency order. A request can therefore start Budget and another independent specialist together, or discover the multi-hop chain Goal Strategy -> Budget -> Spending when the model determines transaction totals are needed. Required dependency failures and cycles fail closed. Optional dependency failures become explicit warnings, and bounded retries, per-agent timeouts, dependency rounds, provider calls, model calls, and model tokens prevent runaway execution.

## Model Strategy

The implemented deployment adapters call Amazon Nova Lite through the Bedrock APAC geographic inference profile and retrieve Education and Policy evidence from separate configured Amazon Bedrock Knowledge Bases. Each collection is independently pinned by corpus version at runtime; stale, malformed, unapproved, or wrong-version chunks are rejected. Requests can be routed among the profile's APAC destination Regions. Nova Lite remains the selected synthetic-demo baseline because the prompt-set-v4 Nova Micro candidate failed the objective dependency gate and did not advance to blinded review; it is not approved for real-data production use.

The selection harness compares at least one lower-cost model against the baseline on:

- Routing and tool-selection accuracy.
- Unsafe-advice refusal and prompt-injection robustness.
- Explanation quality and consistency across writing styles.
- Grounded source use and hallucination rate.
- P50/P95 latency, token usage, and estimated cost.
- Availability in `ap-southeast-1` and whether inference remains in an approved geography.

The current Lite and Micro profiles are invoked from Singapore and remain within the APAC geography, although individual requests may be routed to another listed APAC destination. Global cross-Region inference can route outside that geography and is prohibited unless the privacy owner explicitly approves the data-residency posture. AWS publishes current model IDs and regional inference options in the [Amazon Bedrock model documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/models.html).

The live evaluator initially estimates Nova Lite usage at USD 0.06 per million input tokens and USD 0.24 per million output tokens. These are explicit, configurable assumptions rather than billed-cost telemetry. Confirm them against the current [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) before every formal comparison, and record the rates in the evidence artifact with the token totals.

## Prompt And Model Change Control

Prompt, model, retrieval, tool, capability, or policy changes require a pull request and regenerated evaluation evidence. A change that alters instruction meaning increments the prompt-set version. Prompt set v3 introduced typed, model-generated dependency planning; prompt set v4 adds grounded Budget and Goal Strategy Education instructions while keeping capability authorization deterministic. Current audit metadata includes model provider, model ID, prompt version, route rationale, trace ID, safety findings, task lifecycle, dependency edges, retrieval consumers, model-call duration, token usage, and separate Education/Policy source provenance without recording raw prompts. The backend persists this privacy-safe trace for profile-authorized retrieval. Live evaluation estimates cost from audited tokens and recorded price assumptions; add billed-cost reconciliation before production approval.
