# Security And Guardrails

## Core Principle

Critical safeguards are distributed across all boundaries. The Risk & Compliance Agent is the final validator, not the only control point.

## Controls

- Request validation: every external request is validated before orchestration.
- PII detection: NRIC-like, Singapore phone, email, and card-like values are redacted before model prompts. Access logs never record request bodies.
- Financial sensitivity handling: income, expense, and goal values are treated as sensitive even when not direct identifiers.
- Prompt-injection protection: suspicious user instructions, Unicode-obfuscated attacks, role impersonation, and fake system/instruction tags are blocked before agent execution.
- Indirect prompt-injection protection: retrieved text and display metadata are inspected before use; a suspicious or oversized chunk is quarantined in full rather than partially rewritten and passed onward.
- Tool permission allowlist: agents can call only approved tools for their role.
- Output validation: Investment Education output must include rationale, confidence, uncertainty, and source IDs drawn only from approved grounding. Specialist and Compliance output is quarantined if it contains injection patterns or sensitive data.
- Auditability: privacy-safe structured lifecycle events record routing, task status, RAG counts/topics, compliance disposition, duration, and model usage under one trace identifier without prompts, financial values, retrieved text, or model output.

The staged AWS authentication boundary uses Cognito authorization code flow with PKCE at Streamlit. The frontend exposes only the ID token to its server-side client. The backend accepts RS256 JWTs only after exact issuer, audience, lifetime, subject, and Cognito `token_use=id` validation through the configured JWKS endpoint. An `Authorization` header is never downgraded to API-key authentication when malformed or invalid.

Authorization binds each created profile to the token's immutable `(issuer, subject)` pair. Every profile, transaction, budget, goal, fairness, chat, coach, and trace operation checks that owner before reading or mutating data. Cross-owner and unknown-resource requests receive the same 404 response, and an existing unowned profile cannot be claimed. Multiple profiles may belong to one authenticated identity. Tokens, authorization headers, and financial request bodies are excluded from application traces and logs.

`BACKEND_API_KEY` is retained only as an explicitly enabled automation credential for release smoke, evaluation, and load workflows. Outside local development, it can address only configured synthetic user-ID prefixes; those namespaces are reserved from authenticated profile creation, and the key is never injected into the authenticated frontend task. `AI_SERVICE_API_KEY` remains the separate private backend-to-AI service credential. OIDC activation is fail-closed and must follow the nullable ownership migration using the exact released backend image.

## Initial Blocked Content

- Requests for guaranteed returns.
- Requests for specific securities to buy or sell.
- Requests to bypass policy, reveal prompts, or ignore instructions.
- Requests that ask the system to process credentials or secrets.

## Limitations

Regex controls do not detect every identifier, obfuscated attack, semantic jailbreak, hallucination, or harmful financial recommendation. They are defense-in-depth controls backed by schemas, deterministic tools, source restrictions, output policy checks, evaluations, monitoring, and human governance. Real financial data remains prohibited until a privacy review and stronger DLP strategy are complete.

See `docs/security-risk-register.md` for threat ownership, residual risk, and release acceptance rules.
