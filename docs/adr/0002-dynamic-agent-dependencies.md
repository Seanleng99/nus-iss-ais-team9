# ADR 0002: Dynamic Specialist Dependencies

## Status

Accepted

## Context

A specialist can require a capability produced by another specialist after the initial router has
already selected one or more agents. Direct agent-to-agent calls would bypass centralized data
minimization, authorization, cycle control, failure handling, and auditability.

## Decision

Specialists request capabilities through a typed `needs_dependency` outcome. They do not name,
invoke, or transfer control to another specialist. The orchestrator owns a deterministic capability
registry that maps each capability to its provider and allowed requesters.

For each request, the orchestrator validates authorization and required fields, fingerprints the
provider input, and reuses a matching completed capability when available. Otherwise it schedules
an agent provider or invokes an explicitly supported tool provider, records the dependency edge,
detects cycles where applicable, and resumes the requester with only the validated
`CapabilityResult`. Dependency rounds, provider calls, task attempts, agent duration, model calls,
and model tokens are bounded by configuration.

Prompt set v3 allows eligible specialists to produce a schema-validated `ready`,
`needs_dependency`, or `needs_input` planning result. The implemented chain is Goal Strategy
requesting `monthly_savings_capacity` from Budget; Budget can in turn request
`transaction_category_totals` from Spending when recent transactions are needed. Independent ready
tasks run concurrently. Risk and Compliance remains a mandatory fixed release gate and is not
selected through the dependency mechanism.

Prompt set v4 adds the `education_context` tool capability. Budget and Goal Strategy may request it
only for deterministically allowlisted investment topics. The orchestrator constructs a canonical
topic-only query, invokes `education_retriever`, reuses an identical result within the run, and
records the tool invocation as a dependency provider. Spending and Risk and Compliance are denied
that capability. Optional retrieval failure preserves deterministic calculations and becomes an
explicit evidence gap.

## Consequences

- Dynamic collaboration remains centrally governed and traceable.
- A capability provider can later change from a local tool to an agent or service without changing
  the requesting specialist's contract.
- A dynamic dependency can require an additional model call and increase latency.
- Cycles, duplicate work, unauthorized capabilities, missing fields, and failed required providers
  must fail closed.
- Prompt set v2 remains available as the deterministic compatibility path. Prompt set v3 makes
  dependency discovery model-generated while keeping registry authorization and scheduling under
  deterministic orchestrator control; prompt set v4 governs tool-provided Education dependencies.
