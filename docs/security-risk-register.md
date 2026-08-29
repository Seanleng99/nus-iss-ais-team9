# AI Security Risk Register

Ratings are qualitative for the synthetic-data demo and must be reassessed before production data or users are introduced.

| ID | Risk and impact | Inherent | Current controls and evidence | Detection | Residual | Owner |
|---|---|---:|---|---|---:|---|
| AI-01 | Direct prompt injection changes behavior or exposes hidden instructions | High | Boundary and per-agent inspection; blocked deployment probe; adversarial evals | Block rate and guardrail finding category | Medium | AI/security |
| AI-02 | Instructions embedded in RAG content influence agents | High | Trusted-source allowlist, context sanitization, instruction/data separation | Indirect-injection eval rate and ingestion rejection log | Medium | AI/data |
| AI-03 | Hallucinated or regulated financial advice causes user harm | Critical | Educational scope, deterministic calculations, source IDs, final compliance validation, blocked-advice patterns, disclaimer | Unsafe-advice evals, sampled review, user incident reports | High | Product/compliance |
| AI-04 | PII or sensitive financial data leaks into prompts, logs, or responses | Critical | Data minimization, PII redaction, body-free access logs, private networking, synthetic-data-only demo | PII evals, log sampling, DLP findings | Medium | Privacy/security |
| AI-05 | Unauthorized caller accesses backend or AI service | High | Cognito OIDC with PKCE; exact JWT signature/issuer/audience/lifetime/token-use validation; constrained automation credential; independent backend-to-AI secret; private AI boundary | Sanitized 401 rate, Cognito/CloudTrail findings, and authorization tests | Medium | Backend/cloud |
| AI-06 | Tool misuse or excessive agent authority changes data or calls unapproved capabilities | High | Typed per-agent allowlist; read-only deterministic tools; no transaction execution | Tool-denial tests and audit findings | Low | AI/backend |
| AI-07 | Poisoned, stale, or incorrect knowledge produces misleading education | High | Controlled offline sources, source IDs, retrieval evals, planned provenance/checksum/freshness gate | Recall regression, source-age alarm, ingestion review | Medium | Data/compliance |
| AI-08 | Model, prompt, or data-distribution drift degrades quality or safety | High | Versioned policy and datasets; weekly baseline regression gate; immutable release SHA | Scheduled evaluation artifact and CloudWatch quality metrics | Medium | AI/operations |
| AI-09 | Dependency or container compromise introduces malicious code | High | Dependency review, Dependabot, Bandit SAST, hardened non-root images, ECR/Inspector gate, immutable tags | GitHub workflow evidence and Inspector findings | Medium | Engineering/security |
| AI-10 | Secret disclosure through source, workflow, image, or debug output | Critical | GitHub OIDC, no long-lived AWS keys, `.dockerignore`, GitHub secret scanning plan, sanitized errors | Push protection, secret alerts, credential-use anomalies | Medium | Security/cloud |
| AI-11 | Denial of service or runaway model cost affects availability or budget | High | Backend/AI CPU target tracking, API timeouts, bounded tool/model limits, ALB/ECS health checks, circuit breakers, bounded live/load workflows | CloudWatch latency/error/throttle alarms and privacy-safe token/cost evidence | Medium | Operations/product |
| AI-12 | Audit records are incomplete, mutable, or contain sensitive content | High | Correlation ID, UTC execution time, policy findings, body-free structured logs, owner-scoped trace deletion, 30-day logs and trace purge | Missing-trace metric, purge evidence, and log-access audit | Medium | Operations/security |
| AI-13 | Service-to-service contract drift breaks coaching or bypasses controls | High | Pydantic DTOs, separate API tests, CI end-to-end safety smoke, coordinated deployment | Integration-job failures and 5xx alarm | Low | Backend/AI |
| AI-14 | Cross-Region model inference violates an intended data-residency constraint | High | Synthetic-only demo; model ID and inference scope are explicit; deployment checklist requires residency decision | Configuration review and Bedrock invocation-region records | Medium | Privacy/cloud |
| AI-15 | Authenticated user reads or mutates another user's financial workspace | Critical | Immutable issuer/subject ownership columns; enforcement before every profile-scoped read/write and coach call; non-enumerating 404; unowned-profile takeover prevention; cryptographic and cross-owner tests | Authorization-denial metrics, test evidence, and sampled access review | Low | Backend/security |
| AI-16 | Stolen, replayed, malformed, or wrong-purpose token is accepted | Critical | HTTPS public boundary; short-lived Cognito ID token; RS256 allowlist; exact audience/issuer; required expiry/issued-at/subject; `token_use=id`; 30-second maximum configured skew; no bearer-to-key downgrade | Sanitized authentication failures, Cognito events, and negative JWT tests | Medium | Security/cloud |
| AI-17 | Public HTTP ALB origin bypasses the CloudFront presentation boundary | High | Backend independently enforces JWT or constrained automation identity; AI and RDS remain non-public; synthetic-only restriction | Direct-origin probe and security-group/config review | Medium | Cloud/security |
| AI-18 | CloudFront default-domain certificate cannot enforce the target modern TLS policy | High | HTTPS redirect and encryption in transit; synthetic-only restriction | CloudFront configuration review and protocol probe | Medium | Cloud/security |

## Acceptance Rules

- No Critical residual risk is accepted for the demo.
- Any new real-data, identity, persistent-memory, external-tool, or transaction capability triggers a risk reassessment.
- Critical guardrail and authorization controls require automated tests and cannot be waived by a prompt change.
- Accepted High residual risks require a named owner, expiry date, and documented approval in the final project risk log.
