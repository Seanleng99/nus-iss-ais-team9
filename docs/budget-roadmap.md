# Budget planner roadmap implementation

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

The next authorized increment implements the first two follow-up priorities: explicit shared bill/debt identities and payment/refund reconciliation, plus conversational settings and multi-month planning with clarification and confirmation. Other proposed priorities (cash-flow-aware alternatives, variable-income planning, deeper goal/debt optimization, and adaptive history) remain deferred. See the workspace v1 sections and new regression tests in the planner document.

The bounded implementations and remaining limitations are described in [budget-planning.md](budget-planning.md). Apply database migrations through `20260930_0012` before deployment. The 2026-09-29 AWS release subsequently applied and verified migrations. Deployment and focused live acceptance passed at application revision `f821887`; see the linked planner document for retained evidence.


Workspace v1 local verification (2026-09-30): backend **517 passed**, AI service **1,137 passed / 1 Windows symlink test deselected**, frontend **77 passed**, and live-evaluation harness **48 passed**. Ruff passed across the application code. The expanded nine-case live dataset is prepared but has not been run against a deployment of this change. Previous release/live evidence does not validate the new workspace commands or reconciliation UI.


## Authorized remaining implementation sequence (2026-09-30)

User requested completing all remaining improvements, committing each improvement, and withholding deployment until completion. Sequence:

1. Cash-flow-aware alternatives and Budget/Overview timing views — implemented; 39 backend and 27 frontend targeted tests passed.
2. Variable monthly income, income scenarios and reserves for irregular expenses — implemented; 36 backend and 21 frontend targeted tests passed.
3. Explicit goal/debt trade-off projections.
4. Adaptive reviews and confirmed plan version history/restoration.
5. Income reconciliation, searchable records, match suggestions and explicit refund spending treatment.
6. Precise conversational collection editing and expanded multi-turn verification.
7. Account balances/transfers, duplicate-aware imports and relational reconciliation storage.

Bank-provider integrations, external notification delivery and unattended automatic rollover were identified as separate extensions in the preceding proposal; this sequence implements the listed planner improvements and account/import foundations. No push/release until the sequence and required checks are complete.
