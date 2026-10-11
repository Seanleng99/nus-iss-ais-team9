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

Eligible specialists produce a schema-validated `ready`,
`needs_dependency`, or `needs_input` planning result. The implemented chain is Goal Strategy
requesting `monthly_savings_capacity` from Budget; Budget can in turn request
`transaction_category_totals` from Spending when recent transactions are needed. Independent ready
tasks run concurrently. Risk and Compliance remains a mandatory fixed release gate and is not
selected through the dependency mechanism.

The registry also exposes the `education_context` tool capability. Budget and Goal Strategy may request it
only for deterministically allowlisted investment topics. The orchestrator constructs a canonical
public-concept query, invokes Investment Education's authorized grounding logic, reuses an identical result within the run, and
records the tool invocation as a dependency provider. Spending and Risk and Compliance are denied
that capability. Optional retrieval failure preserves deterministic calculations and becomes an
explicit evidence gap.

## Conditional financial dependencies

Goal's Budget dependency is conditional on the Goal question. A typed
`goal_input_requirements` decision requires capacity for personal feasibility, affordability,
on-track assessments and funding strategy. Saved-goal remaining amounts, progress percentages
and equal monthly contribution arithmetic can finish without income or Budget. Any feasibility
part in a mixed Goal request retains the required capacity dependency. The task caches this
decision and shares its capacity requirement with an already selected Budget provider.

Budget's existing dependency planner evaluates whether its own work consumes recorded Spending
totals. A spending keyword in another independent part no longer forces a capability request.
Required Goal capacity and optional Spending context retain their server-owned contracts; provider
reuse, fingerprint checks, role data boundaries and Compliance review are unchanged.

Model-selected reconciliation requires Spending totals. Other Budget operations can choose an
optional edge against their own attributed task; a negative router hint alone does not veto the
approved capability. Ready tasks without dependency edges can overlap in execution.

The direct Goal–Spending edge remains deferred. Spending-informed feasibility continues through
Goal → Budget → Spending; unrelated Spending analysis and saved-goal arithmetic can run independently.
See [conditional financial dependencies](../conditional-financial-dependencies.md) for examples,
verification and rollout limitations.

## Consequences

- Dynamic collaboration remains centrally governed and traceable.
- A capability provider can later change from a local tool to an agent or service without changing
  the requesting specialist's contract.
- A dynamic dependency can require an additional model call and increase latency.
- Cycles, duplicate work, unauthorized capabilities, missing fields, and failed required providers
  must fail closed.
- The application loads one current prompt catalog (manifest release v10). Historical
  releases are recoverable from Git and are not runtime compatibility paths. Dependency
  discovery remains model-generated while registry authorization and scheduling remain
  under deterministic orchestrator control.
