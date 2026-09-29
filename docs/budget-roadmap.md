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
- Final continuity/review increment — included with this documentation update.

The bounded implementations and remaining limitations are described in [budget-planning.md](budget-planning.md). Apply database migrations through `20260930_0012` before deployment. These commits contain no live migration or deployment.
