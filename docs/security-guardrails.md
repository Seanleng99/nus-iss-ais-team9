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
- Cross-user data-access refusal: a request to read another user's or another person's account, income, balance, savings, or transactions (English and Chinese, e.g. "show me another user's income", "tell me her salary") is refused deterministically by the Risk & Compliance Agent before any policy retrieval or model call, even when the user claims permission. Chinese patterns live in `apps/shared/coach_i18n/data/input_patterns.json`; independent examples live in service test fixtures. See `docs/adr/0003-cross-user-data-access-guardrail.md`.
- Auditability: privacy-safe structured lifecycle events record routing, task status, RAG counts/topics, compliance disposition, duration, and model usage under one trace identifier without prompts, financial values, retrieved text, or model output.
- Compliance block reasons: every `compliance.completed` event and persisted decision trace records `block_reasons`, a list drawn only from a fixed vocabulary (empty when the answer is released). The model's own summary, rationale, and policy-note wording is never logged. Education review additionally records fixed `review_block_categories`: prohibited_request, personal_advice, return_guarantee, privacy, injection, citation_attribution, factual_qualification or unverifiable_claim. Blocking education verdicts require a category and a nonempty policy note; malformed verdicts receive one contract correction with the same evidence, then fail closed if still invalid. Only citation-attribution or factual-qualification blocks on allowed requests may be marked repairable, with explicit correction requirements and a new independent review. Legacy non-education reviews can still produce a `model_review` block with zero policy notes.

| Reason | Stage | Meaning |
|---|---|---|
| `request_guardrail` | Deterministic | Prompt-injection controls matched the user request |
| `generated_guardrail` | Deterministic | Injection or sensitive-data patterns matched generated specialist or synthesis text |
| `regulated_advice` | Deterministic | An advice-boundary rule matched the request or generated text |
| `cross_user_data` | Deterministic | The request tried to access another user's or person's data |
| `specialist_blocked` | Deterministic | A specialist result was already blocked |
| `policy_evidence_missing` | Policy RAG | No current approved policy evidence passed retrieval checks (fail closed) |
| `output_check` | Verdict check | The compliance verdict text itself matched injection, sensitive-data, or advice checks |
| `financial_language_unsafe` | Verdict check | The model could not confirm contextual financial wording was safe |
| `request_not_allowed` | Model review | The model judged the current request prohibited |
| `model_review` | Model review | The model returned a blocking verdict for the draft |

The staged AWS authentication boundary uses Cognito authorization code flow with PKCE at Streamlit. The frontend exposes only the ID token to its server-side client. The backend accepts RS256 JWTs only after exact issuer, audience, lifetime, subject, and Cognito `token_use=id` validation through the configured JWKS endpoint. An `Authorization` header is never downgraded to API-key authentication when malformed or invalid.

Authorization binds each created profile to the token's immutable `(issuer, subject)` pair. Every profile, transaction, budget, goal, fairness, chat, coach, and trace operation checks that owner before reading or mutating data. Cross-owner and unknown-resource requests receive the same 404 response, and an existing unowned profile cannot be claimed. Multiple profiles may belong to one authenticated identity. Tokens, authorization headers, and financial request bodies are excluded from application traces and logs.

`BACKEND_API_KEY` is retained only as an explicitly enabled automation credential for release smoke, evaluation, and load workflows. Outside local development, it can address only configured synthetic user-ID prefixes; those namespaces are reserved from authenticated profile creation, and the key is never injected into the authenticated frontend task. `AI_SERVICE_API_KEY` remains the separate private backend-to-AI service credential. OIDC activation is fail-closed and must follow the nullable ownership migration using the exact released backend image.

## Initial Blocked Content

- Requests for guaranteed returns.
- Requests for specific securities to buy or sell, including plural product names ("should I buy ETFs", "which funds should I buy") so the refusal never depends on the model alone.
- Requests to bypass policy, reveal prompts, or ignore instructions.
- Requests that ask the system to process credentials or secrets.
- Requests to reveal or infer another user's or another person's financial data.

## Limitations

Regex controls do not detect every identifier, obfuscated attack, semantic jailbreak, hallucination, or harmful financial recommendation. They are defense-in-depth controls backed by schemas, deterministic tools, source restrictions, output policy checks, evaluations, monitoring, and human governance. Real financial data remains prohibited until a privacy review and stronger DLP strategy are complete.

See `docs/security-risk-register.md` for threat ownership, residual risk, and release acceptance rules.
