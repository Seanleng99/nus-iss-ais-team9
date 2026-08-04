# Security And Guardrails

## Core Principle

Critical safeguards are distributed across all boundaries. The Risk & Compliance Agent is the final validator, not the only control point.

## Controls

- Request validation: every external request is validated before orchestration.
- PII detection: NRIC-like, Singapore phone, email, and card-like values are redacted before model prompts. Access logs never record request bodies.
- Financial sensitivity handling: income, expense, and goal values are treated as sensitive even when not direct identifiers.
- Prompt-injection protection: suspicious user instructions are blocked or downgraded before agent execution.
- Indirect prompt-injection protection: retrieved documents are sanitized and metadata-isolated before being used as context.
- Tool permission allowlist: agents can call only approved tools for their role.
- Output validation: agent output must include rationale, confidence, and advisory boundaries.
- Auditability: execution metadata and policy decisions are logged with trace identifiers.

Service authentication uses separate frontend-to-backend and backend-to-AI keys in the synthetic demo. The AI service is private. OIDC/JWT user identity and authorization are required before real users; service keys are not a substitute for end-user authentication.

## Initial Blocked Content

- Requests for guaranteed returns.
- Requests for specific securities to buy or sell.
- Requests to bypass policy, reveal prompts, or ignore instructions.
- Requests that ask the system to process credentials or secrets.

## Limitations

Regex controls do not detect every identifier, obfuscated attack, semantic jailbreak, hallucination, or harmful financial recommendation. They are defense-in-depth controls backed by schemas, deterministic tools, source restrictions, output policy checks, evaluations, monitoring, and human governance. Real financial data remains prohibited until a privacy review and stronger DLP strategy are complete.

See `docs/security-risk-register.md` for threat ownership, residual risk, and release acceptance rules.
