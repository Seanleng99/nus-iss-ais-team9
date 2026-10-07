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
An older single-specialist router response can retain the complete question, with
unknown requirements classified by that specialist. Mixed responses must provide
the attributed task split. Assignment questions and quotes stay private to the run;
they are omitted from exported audit metadata.
Targeted checks cover independent scopes, adversarial over-requesting and invalid
assignment provenance alongside the existing financial dependency regressions.

## 2. Follow-up subjects and displayed option identity

Unsupported clauses no longer erase explicit supported subjects before answerability.
Reviewed rendered options replace the router's preliminary numbered referents.
Persistence collapses aliases with the same position, option index, owner and canonical
topics, while conflicting identities remain ambiguous. Malformed historical metadata
can fall back to the available displayed option set using the existing dialogue
boundaries. Unavailable answers and genuinely missing subjects still clarify.

## 3. Semantic Education grounding

The v9 router assigns canonical educational topics to each task according to the
meaning of its question. Budget and Goal request grounding from that assignment,
not whole-question vocabulary matches. The generic `pool`/`pooled` aliases are
removed. Shared goal funding is arithmetic; explaining investment pooling remains
an educational request. A separately selected Education specialist continues to
own the independent educational part. Emergency-fund aggregates use Goal's scope.

## 4. Deadlines and redundant calls

An 85-second AI workflow deadline fits inside the backend's configured 90-second
request timeout. The deadline is inherited by specialist threads and model correction
calls. Provider requests respect remaining time; backend traces record their effective
timeout and distinguish workflow, specialist, model and transport expiration.
The private stream carries a backend-supplied remaining workflow limit, which can
only shorten the AI service's own deadline and reserves five seconds for transport.
Model-supplied task requirements avoid redundant classification. A complete single
read-only specialist answer is reused before independent compliance review.

The attempted ECS timeout inspection was blocked by expired AWS CLI credentials.
The actual deployed limits and the historical 45-second cutoff remain unverified;
this change does not claim to have modified a deployed ECS service.
