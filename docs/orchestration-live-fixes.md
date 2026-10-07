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

## 5. Financial review and bounded correction

v9 financial writers retain a private, fingerprinted grounding snapshot. Review
identifies defects by server-owned section ID. An allowed factual-qualification
defect can receive one correction using unchanged task inputs and tool results,
then a second independent review. Prohibited advice, unverifiable claims, changed
authority, missing usage, exhausted budgets and unavailable inputs do not authorize
correction. A rejected or unavailable correction remains withheld.

`REVIEW_DIAGNOSTICS_DIR` enables redacted diagnostic files containing the rejected
draft, verdict, section ownership and original financial grounding. They never enter
public traces or responses. The ECS template uses a private ephemeral `/tmp` folder;
retention is at most 128 files, with 24-hour expiry enforced on subsequent writes.
Operator access is required. Local diagnostics are disabled unless configured.

## 6. Spending analysis and comparison periods

The router supplies Spending's own calendar scope and optional primary analysis
month. Budget retains its independent scope. November's zero-record result remains
the main analysis even when October has comparison records. Aggregate grounding
keeps the primary totals, comparison rows and earlier history distinct. Raw dated
records can supply multi-month aggregates without borrowing another month's totals.
Unclear periods clarify. Validated scopes survive the content-free trace boundary.
Capability fingerprints bind produced expense totals to their actual task inputs.

## 7. Evaluation that exposes semantic gaps

`app/evals/datasets/orchestration_live_regression_v1.json` freezes all 34 approved
original turns, excluding the two historical retests. Its reconstructed synthetic
profile retains published monthly totals, recorded coverage, saved capacities and
goal arithmetic; it is not an export of the application ledger. Expectations never
enter runtime routing. The evaluator forbids specialist overrides and runs the same
orchestrator with either the fixture or an explicitly selected production provider.
It records initial/final agents, authorized dependency ownership, observed task
overlaps, calendar/financial facts, review outcomes, safe failures and answers for
human review. Follow-ups use the preceding available answer and canonical referents.

Repeated runs record provider/model policies, temperatures, prompt version, build
identity and suite hash. Passing graph/number checks does not establish answer
quality: content checks and reviewed sources remain a required human step. A fixture
report is explicitly `offline_fixture_contract`; a real-provider report is
`in_process_production_model`. Neither proves browser/backend transport configuration.
The existing Edge evidence remains the historical deployment result.

From `apps/ai-service`, first verify the harness without paid model calls:

```powershell
../../.venv/Scripts/python.exe -m app.evals.orchestration_acceptance --suite app/evals/datasets/orchestration_live_regression_v1.json --provider local_fixture --build-commit <tested-commit> --repeats 1 --output ../../artifacts/reasoning-fixture.json
```

To measure semantic behavior with authenticated model configuration, use
`--provider openai --repeats 3` and a separate output. This invokes the real router,
requirement classifiers, planners, writers and independent reviewer; there is no
expected-agent override. Preserve failed routes rather than tuning the fixture or
prompts to individual case IDs. After deployment, repeat the approved Edge prompts
to verify application context, recurrence lookup paths and actual transport limits.

The integration checks also bind conditional Education grounding to its requester,
retain confirmed capacity arithmetic when raw income is unnecessary, and prevent
Education correction from taking ownership of financial review defects. Diagnostic
filenames are normalized UUIDs so retention remains bounded without path injection.
When Goal's model-selected feasibility needs capacity from an already selected
conceptual Budget task, Budget can produce the deterministic capacity capability
without replacing its separate conceptual narrative. This preserves both assignments.

No production-model or new deployed-browser acceptance run was performed for these
source changes. AWS credentials expired during the read-only deployed timeout check.

## Source verification

| Check | Result |
|---|---|
| Full AI service suite | 1,856 passed; one skip |
| Full backend suite | 942 passed |
| Shared contracts and arithmetic | 46 passed |
| Infrastructure scripts | 331 passed; five skips; 16 subtests passed |
| Changed Python lint, whitespace and language-resource scan | Passed |
| Frozen 34-turn fixture matrix | 17 graph/fact/overlap checks passed; acceptance remains pending |

The fixture matrix intentionally preserves failures from its older keyword router,
unsupported numbered-option fixture output, and fast tasks without observed overlap.
It also exposes fixture requirement misclassification on confirmed-capacity phrasing.
Those results are harness evidence, not measured production-model accuracy. Do not
interpret the passing unit suites as 34 successful live answers. The final evaluator
and financial/provider integration checks also passed a targeted 14-test run.
Windows ASGI and infrastructure subprocess tests required execution outside the
sandbox; pytest temporary directories were confined to workspace artifacts.
