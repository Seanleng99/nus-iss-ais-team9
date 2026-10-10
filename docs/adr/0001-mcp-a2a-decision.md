# ADR 0001: MCP And A2A Use

## Status

Implemented in the current runtime; the original proposal is retained as design history.

## Context

The module FAQ states that MCP and A2A are not mandatory, but teams must understand and justify whether they are relevant.

## Decision

The initial implementation does not require MCP or A2A.

The AI service exposes internal tools through a typed registry with explicit allowlists. This is sufficient for the current project because all agents run in one service and use a small controlled set of tools.

## Consequences

- Lower implementation complexity for the practice module.
- Easier end-to-end tracing and policy enforcement.
- MCP can be introduced later to expose retrieval, calculator, or policy tools through a standard interface.
- A2A can be introduced later if specialist agents are split into independently deployed services.
