# AI Security Risk Register

Ratings are qualitative for the synthetic-data demo and must be reassessed before production data or users are introduced.

| ID | Risk and impact | Inherent | Current controls and evidence | Detection | Residual | Owner |
|---|---|---:|---|---|---:|---|
| AI-01 | Direct prompt injection changes behavior or exposes hidden instructions | High | Boundary and per-agent inspection; blocked deployment probe; adversarial evals | Block rate and guardrail finding category | Medium | AI/security |
| AI-02 | Instructions embedded in RAG content influence agents | High | Trusted-source allowlist, context sanitization, instruction/data separation | Indirect-injection eval rate and ingestion rejection log | Medium | AI/data |
| AI-03 | Hallucinated or regulated financial advice causes user harm | Critical | Educational scope, deterministic calculations, source IDs, final compliance validation, blocked-advice patterns, disclaimer | Unsafe-advice evals, sampled review, user incident reports | High | Product/compliance |
| AI-04 | PII or sensitive financial data leaks into prompts, logs, or responses | Critical | Data minimization, PII redaction, body-free access logs, private networking, synthetic-data-only demo | PII evals, log sampling, DLP findings | Medium | Privacy/security |
| AI-05 | Unauthorized caller accesses backend or AI service | High | Separate service keys, constant-time comparison, Secrets Manager plan, private AI boundary, least-privilege security groups | Authentication failures and CloudTrail/IAM findings | Medium | Backend/cloud |
| AI-06 | Tool misuse or excessive agent authority changes data or calls unapproved capabilities | High | Typed per-agent allowlist; read-only deterministic tools; no transaction execution | Tool-denial tests and audit findings | Low | AI/backend |
| AI-07 | Poisoned, stale, or incorrect knowledge produces misleading education | High | Controlled offline sources, source IDs, retrieval evals, planned provenance/checksum/freshness gate | Recall regression, source-age alarm, ingestion review | Medium | Data/compliance |
| AI-08 | Model, prompt, or data-distribution drift degrades quality or safety | High | Versioned policy and datasets; weekly baseline regression gate; immutable release SHA | Scheduled evaluation artifact and CloudWatch quality metrics | Medium | AI/operations |
| AI-09 | Dependency or container compromise introduces malicious code | High | Dependency review, Dependabot, CodeQL, hardened non-root images, ECR/Inspector gate, immutable tags | GitHub alerts and Inspector findings | Medium | Engineering/security |
| AI-10 | Secret disclosure through source, workflow, image, or debug output | Critical | GitHub OIDC, no long-lived AWS keys, `.dockerignore`, GitHub secret scanning plan, sanitized errors | Push protection, secret alerts, credential-use anomalies | Medium | Security/cloud |
| AI-11 | Denial of service or runaway model cost affects availability or budget | High | ECS autoscaling plan, API timeouts, bounded tool set, ALB/ECS health checks, circuit breakers | Latency/error/token/cost alarms | Medium | Operations/product |
| AI-12 | Audit records are incomplete, mutable, or contain sensitive content | High | Correlation ID, UTC execution time, policy findings, body-free structured logs, CloudWatch retention plan | Missing-trace metric and log-access audit | Medium | Operations/security |
| AI-13 | Service-to-service contract drift breaks coaching or bypasses controls | High | Pydantic DTOs, separate API tests, CI end-to-end safety smoke, coordinated deployment | Integration-job failures and 5xx alarm | Low | Backend/AI |
| AI-14 | Cross-Region model inference violates an intended data-residency constraint | High | Synthetic-only demo; model ID and inference scope are explicit; deployment checklist requires residency decision | Configuration review and Bedrock invocation-region records | Medium | Privacy/cloud |

## Acceptance Rules

- No Critical residual risk is accepted for the demo.
- Any new real-data, identity, persistent-memory, external-tool, or transaction capability triggers a risk reassessment.
- Critical guardrail and authorization controls require automated tests and cannot be waived by a prompt change.
- Accepted High residual risks require a named owner, expiry date, and documented approval in the final project risk log.
