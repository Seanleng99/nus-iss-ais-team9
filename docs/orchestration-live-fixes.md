# Fixes following the October 2026 live evaluation

These changes address the findings in `agent-reasoning-live-test-results-2026-10-07.md`.
Semantic decisions remain model-owned. Code validates attribution, capability ownership,
financial evidence, calendar arithmetic and execution bounds. Evaluation expectations
are not runtime routing rules. Historical v9 live evidence predates these changes;
identify the deployed build commit as well as the prompt version when retesting.

## 1. Scoped specialist work

The v9 router produces one attributed `task_assignments` entry per selected specialist.
Each specialist receives its assigned question. Budget's model-selected
`requires_spending` determines whether recorded-total dependencies are available to
its planner; the presence of records alone is insufficient. An actual-versus-plan
assessment can still need Spending even with a confirmed budget. Providers added
dynamically inherit the requesting task's question instead of unrelated clauses.

Structural validation rejects duplicate, incomplete or unattributed assignments and
allows the existing bounded structured-response correction. Original user wording
remains the synthesis input. Legacy prompt versions preserve their existing contract.
Targeted checks cover independent scopes, adversarial over-requesting and invalid
assignment provenance alongside the existing financial dependency regressions.
