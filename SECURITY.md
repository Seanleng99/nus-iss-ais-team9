# Security Policy

## Supported Scope

The current repository is a synthetic-data educational demo. It must not receive real banking credentials, government identifiers, customer financial records, or transaction exports.

## Reporting

Do not open a public issue containing a vulnerability, secret, personal data, prompt transcript, or AWS account detail. Report it privately to the project security owner through the repository's private vulnerability-reporting channel. Include affected commit, service, reproduction steps using synthetic data, impact, and relevant correlation IDs.

## Secret Exposure

If a credential is committed or printed, revoke or rotate it immediately, review its use in CloudTrail and application logs, remove it from deployment configuration, and add a regression control. Rewriting Git history does not make an exposed credential safe.

## Release Security Baseline

- No default service key outside local mode.
- No Critical or High container finding above policy.
- All authorization, prompt-injection, PII, RAG sanitization, and tool-permission tests pass.
- GitHub OIDC is used instead of stored AWS access keys.
- The AI service has no public ingress.
- Real user access is blocked until OIDC/JWT authorization and privacy controls are implemented.

See `docs/security-risk-register.md` and `docs/security-guardrails.md` for the threat model and control limitations.
