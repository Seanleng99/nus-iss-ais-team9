# Data lifecycle and user rights

## Status and scope

`data-lifecycle-v1`, effective 2026-08-31, governs application records for the synthetic-data AWS demo. The machine-readable source of truth is `apps/backend/app/policies/data-lifecycle-policy.json`. Runtime settings may shorten an automatic period, but changing the policy, enabling durable memory, or extending retention requires reviewed source control and a release.

This control set does not approve real personal financial data or production use. A formal privacy review, representative-user validation, and production operating approval remain required.

## Retention classes

| Data class | Retention | Enforcement |
| --- | --- | --- |
| Authenticated financial workspace: profile, transactions, goals, budgets, fairness data, and consent records | Until the owner deletes the workspace | Owner-scoped deletion API and database cascades |
| Chat sessions and messages | 90 days after the conversation was last updated | Weekly one-shot lifecycle task |
| Detailed orchestration traces | 30 days after creation | Weekly one-shot lifecycle task; individual owner-scoped deletion also remains available |
| Synthetic automation users whose IDs use an approved automation prefix | 30 days after stored-data activity | Weekly one-shot lifecycle task |
| Optional fairness demographics | Until consent withdrawal or workspace deletion | Withdrawal deletes demographics immediately |
| Durable agent memory | Not active | Versioned consent preference only; consent does not activate the disabled feature |

Backend-derived session facts, clarification state and bounded older-dialogue excerpts are part of the retained chat, not a separate cross-chat memory feature. They appear in the owner data export and are deleted with the chat, on chat expiry, or with the workspace. They do not alter saved financial records. See [Session context](session-context.md).

The synthetic-user rule deliberately requires both an unowned database identity and an allowlisted automation prefix. It cannot expire an OIDC-bound user or an unowned legacy identifier outside that namespace. Read-only access is not treated as stored-data activity. The weekly task emits only policy version, timestamps, cutoffs, and aggregate deletion counts—never profile IDs, prompts, answers, or financial values.

## Owner controls

All routes reuse the backend's issuer/subject ownership boundary or the tightly scoped synthetic automation identity:

- `GET /api/users/{user_id}/data-lifecycle` returns the active policy and durable-memory consent state.
- `PUT /api/users/{user_id}/memory-consent` records or withdraws consent version `1.0`. Durable memory remains disabled by policy and runtime configuration.
- `GET /api/users/{user_id}/data-export` returns a versioned JSON export of the profile, demographics, consent history, transactions, goals, budgets, conversations, citations, and unexpired decision traces. Authentication identity claims are excluded.
- `DELETE /api/users/{user_id}/data` requires the exact profile ID and current policy version in the request body. It deletes the user row and all owned application data in one transaction, then returns a privacy-safe receipt containing a random request ID, completion time, policy version, and aggregate record counts.

The Streamlit `Privacy & data` tab exposes the same lifecycle summary, consent preference, export, and confirmed deletion flow. Users should export before deleting if they need a copy. Deletion is immediate and cannot be undone from the application.

These routes delete the active application store. The RDS template retains
automated backups for one day and preserves snapshots on stack deletion or
replacement. Expiry of manual/final snapshots and reconciliation of deleted
workspaces or withdrawn consent after a restore have not been demonstrated.
Do not describe workspace deletion as erasure of every retained backup; see
[AI-21 and AI-22](security-risk-register.md#risks-and-implemented-controls).

## Scheduled enforcement

When enabled by repository variable `AWS_OPERATIONAL_VALIDATION_ENABLED=true`, the Sunday 10:00 Singapore AWS operational workflow runs the lifecycle task below in an independent `retention` job; manual dispatch runs it regardless of that switch. The job requires only the deployment role, cluster, backend service and backend container configuration. Operational environment, alarm or edge failures in the separate validation job cannot prevent the purge. Retention failures still fail the workflow, and `aws-retention-evidence-<run-id>` retains the task result for 90 days. A policy value alone does not prove that the purge job ran:

```text
python -m app.jobs.purge_data_lifecycle
```

The task uses `TRACE_RETENTION_DAYS=30`, `CHAT_RETENTION_DAYS=90`, `SYNTHETIC_USER_RETENTION_DAYS=30`, and the deployed automation prefixes. The release workflow rejects backend task definitions whose lifecycle configuration drifts from the reviewed demo values. Unit tests cover scope, cascades, ownership isolation, stale-policy rejection, export minimization, and repeat-run idempotency.

## Governance changes

Any change to categories, periods, export schema, consent purpose/version, memory enablement, or deletion semantics requires:

1. a new policy version and effective date;
2. compatible migration and API/UI changes;
3. boundary, cascade, retention, and cross-user tests;
4. a reviewed release and successful operational lifecycle task; and
5. updated privacy and requirements records.

Do not infer consent for a new purpose from either fairness consent or durable-memory consent. If durable memory is later implemented, it needs purpose-limited storage, correction and deletion behavior, isolation tests, encryption review, retention enforcement, and a fresh explicit activation decision.
