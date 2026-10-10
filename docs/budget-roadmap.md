# Budget planner roadmap implementation

This roadmap preserves dated implementation checkpoints, including their original “local”, “pending” and no-release instructions; they are not current deployment status or active instructions. The changes are checked into the current code. [Budget usability](budget-usability.md) supersedes the old standalone form/reminder entry points, and [CI and LLMSecOps](agent-test-workflows.md) supersedes the former Budget live workflow. Historical test counts remain unchanged.

## Saved budget management — 5 October 2026

Implemented locally: owned budget listing and saved-month/year comparisons; explicit single-month and multi-month limit/planning edits; category removal and monthly-budget deletion through Coach's preview/confirmation flow. Scope selection now overrides the sidebar default consistently for saved savings capacity and goal feasibility. Batch changes validate every target and apply atomically. Transactions and other financial records are retained; deletion keeps restorable budget history. Coach labels the sidebar context as a default month. No database migration is required. Local regression results and contract details are recorded in `budget-planning.md`; these changes are not yet deployed or certified by live-provider acceptance.

## Everyday reasoning — 5 October 2026

The local 5 October reasoning follow-up addresses ordinary-task context gaps: saved categories and commitments reach advisory turns, calendar scopes also select spending evidence, historical-only spending remains available, recurring expenses use explicit schedule terms and general explanations use semantic input requirements. No new specialist financial features or database migration are required. Verification and remaining live-acceptance limits are recorded in `budget-planning.md`.

## Earlier planner increments

The user authorized these four increments, to be delivered and committed in sequence.

1. **Shared calculations**: owned, month-specific confirmed budget capacity feeds Budget and Goal Strategy; explicit fallback; one shared pool for concurrent goals. Implemented; backend regression suite and AI regression cases verified.
2. **Cash-flow foundation**: typed transactions, explicit bill and income schedules, an opening balance and cash-flow timeline. Recurring transactions alone do not establish a schedule. Implemented as an owned cash-flow workspace with explicit settlement of occurrences.
3. **Funded alternatives**: user-selected protected categories and minimums; goal contributions and debt commitments; deterministic alternatives with an exact preview and explicit save confirmation. Implemented in the Budget workspace and Coach funded-alternatives flow; repository and Coach previews enforce confirmed minimums.
4. **Continuity and reviews**: next-month drafts with user-selected carry-forward rules; opt-in review preferences and due reviews. Implemented with atomic, expiring batch previews and in-app weekly/monthly due reviews in Budget and Overview. All saves require confirmation; no background notifications or automatic rollover.

Each increment includes tests and updates to the planner documentation. Existing confirmed-write and ownership checks remain in force. Live-model acceptance and deployment are separate from local implementation.


Commits delivered in order:

- `a00938a` — shared confirmed-plan calculations.
- `5eb748b` — typed ledger and cash-flow workspace.
- `39c4f42` — confirmed commitments and funded alternatives.
- `8294f6c` — confirmed multi-month plans and opt-in reviews.

The next authorized increment implements the first two follow-up priorities: explicit shared bill/debt identities and payment/refund reconciliation, plus conversational settings and multi-month planning with clarification and confirmation. Those follow-up priorities are now covered by the authorized sequence below. See the workspace v1 sections and new regression tests in the planner document.

The bounded implementations and remaining limitations are described in [budget-planning.md](budget-planning.md). The retained implementation requires database migrations through `20260930_0012` before deployment. The 2026-09-29 AWS release subsequently applied and verified migrations. Deployment and focused live acceptance passed at application revision `f821887`; see the linked planner document for retained evidence.


Workspace v1 local verification (2026-09-30): backend **517 passed**, AI service **1,137 passed / 1 Windows symlink test deselected**, frontend **77 passed**, and live-evaluation harness **48 passed**. Ruff passed across the application code. The expanded nine-case live dataset is prepared but has not been run against a deployment of this change. Previous release/live evidence does not validate the new workspace commands or reconciliation UI.


## Authorized remaining implementation sequence (2026-09-30)

User requested completing all remaining improvements, committing each improvement, and withholding deployment until completion. Sequence:

1. Cash-flow-aware alternatives and Budget/Overview timing views — implemented; 39 backend and 27 frontend targeted tests passed.
2. Variable monthly income, income scenarios and reserves for irregular expenses — implemented; 36 backend and 21 frontend targeted tests passed.
3. Explicit goal/debt trade-off projections — implemented; deterministic rate/fee/repayment and shared-pool tests pass (21 backend tests).
4. Adaptive reviews and confirmed plan version history/restoration — implemented; full backend suite passed (529 tests), including restoration, stale previews and repeated-overrun evidence.
5. Income reconciliation, searchable records, match suggestions and explicit refund spending treatment — implemented; 36 backend and two focused frontend tests passed.
6. Precise conversational collection editing and expanded multi-turn verification — implemented; explicit item edits preserve unrelated settings, with clarification/correction/confirmation/cancel/stale regression coverage.
7. Final storage/account increment — removed by user on 2026-10-01. Relational reconciliation storage, account balances, account-to-account transfers and duplicate-aware CSV imports are all deferred. The release retains the existing owned JSON reconciliation storage.

Bank-provider integrations, external notification delivery and unattended automatic rollover were identified as separate extensions in the preceding proposal; this release implements the first six planner improvements. The seventh increment is deferred by explicit user choice. No push/release until the sequence and required checks are complete.


Retained-scope local checks (2026-10-01, before integrating newer remote main): backend **535 passed**, frontend **77 passed**, live-evaluation harness **50 passed**, Ruff and Bandit passed. The AI suite passed **1,137 tests** (one Windows symlink test excluded). The broader infrastructure suite passed 177 tests with five skips; one existing Bash-dependent release test could not run successfully on this Windows host and must pass in Linux CI before deployment. No account/import/relational-storage code or migration remains.

Integration note: newer remote main includes migration `20260930_0013_pending_goal.py` for conversational Goals. That existing Goal migration is retained; it is unrelated to the removed Budget storage proposal. Deploy using `alembic upgrade head`.

Integrated local verification (2026-10-01): backend **590 passed**, AI service **1,160 passed / 1 Windows symlink test deselected**, frontend **79 passed**. The routing merge preserves both Goal and Budget workspace request handling. Ruff passed. Linux CI, deployment and current-revision live acceptance remain pending at this checkpoint.


Initial retained release at `c1bb993`: [CI 36744555801](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36744555801) and [AWS release 36745028293](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36745028293) passed. [Live acceptance 36746570848](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36746570848) passed 11/18 cases; three request types were intercepted by local recurring/date handlers and one funded-alternative repetition was blocked. Multi-turn checks were skipped because the preceding step failed. The routing fix gives Budget workspace and budget messages precedence over those read handlers, with regression tests; the workflow now runs multi-turn checks independently and records blocking diagnostics. This initial result is not a successful acceptance result.

The routing correction `d058c5e` passed [CI 36796171559](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36796171559), but [release 36796452316](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36796452316) stopped at the ECR/Inspector scan gate before deployment. The previously deployed revision remains `c1bb993`.

User authorized simplifying improvements 4–13 on 2026-10-01. [budget-usability.md](budget-usability.md) describes the smaller everyday editor, automatic spending review, single-change comparison, next-month copy and optional specialist tools, plus request-scoped Coach context and comparisons without mandatory commitments setup. Confirmation, ownership and deterministic checks are retained. This simplification is local and has not been deployed or live-model accepted.

Simplification local verification: backend **601 passed**, frontend **85 passed**, AI service **1,162 passed** with one existing Windows symlink test blocked by OS privileges. Focused final AI and UI checks passed. Ruff and CI-threshold Bandit passed. The new commit requires Linux CI and fresh deployed live-model acceptance before its behavior can be described as release-verified.
