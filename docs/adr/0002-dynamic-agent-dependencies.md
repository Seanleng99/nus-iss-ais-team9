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

For each request, the orchestrator validates authorization and required fields, reuses a completed
capability when available, otherwise schedules its provider, records the dependency edge, detects
cycles, and resumes the requester with only the validated `CapabilityResult`. Dependency rounds and
task attempts are bounded by configuration.

The initial vertical slice is Goal Strategy requesting `monthly_savings_capacity`. Budget produces
that capability from `budget_calculator`. Risk and Compliance remains a mandatory fixed release gate
and is not selected through the dependency mechanism.

## Consequences

- Dynamic collaboration remains centrally governed and traceable.
- A capability provider can later change from a local tool to an agent or service without changing
  the requesting specialist's contract.
- A dynamic dependency can require an additional model call and increase latency.
- Cycles, duplicate work, unauthorized capabilities, missing fields, and failed required providers
  must fail closed.
- The active v2 narrative prompt contract remains unchanged; dependency discovery is currently a
  typed specialist preflight. A future model-generated dependency contract requires a versioned
  prompt-set change and evaluation evidence.
