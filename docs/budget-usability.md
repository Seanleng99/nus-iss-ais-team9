# Everyday Budget and Coach workflow

Implemented locally on 2026-10-01. This document supersedes the earlier UI entry points in `budget-planning.md`; calculation and confirmation contracts remain in force. Deployment and live-model acceptance must be recorded separately.

## Everyday Budget page

The page starts with **Your plan**, followed by **Spending this month** and **Explore a change**.

- Category-only tracking remains available without income. New category amounts start blank; zero must be entered explicitly.
- **Include take-home income and savings** creates a planned budget directly in the main editor. Both amounts start blank for new plans. Existing confirmed settings are preserved, including the chosen method.
- The editor updates planned expenses, savings and unallocated income/shortfall as amounts change. One confirmation states that the income is actual take-home income and the limits include all expenses. Saving still checks affordability, method requirements and saved restrictions in the backend.
- Recorded spending reviews load automatically and can be refreshed. Category/pace details and adjustment proposals are optional. Reviews stay read-only; an adjustment fills an unsaved editor draft and needs confirmation before saving. Cached reviews are invalidated when the saved budget/spending response or Singapore date changes.
- **Explore a change** changes one income, savings or category amount. Users do not need to choose a budgeting method, provide three income cases or name a scenario. Results disclose shortfalls and saved restrictions. Adopting a result changes only the unsaved editor; changing comparison inputs hides obsolete results.
- **Use this plan next month** previews a copy of saved limits with explicitly reviewed income and savings. It requires expense-coverage confirmation, detects existing target plans and requires explicit overwrite permission. Changing inputs hides the old preview. More months and surplus/net carry rules remain advanced options.
- **Discuss my saved budget with Coach** opens Coach with the selected month retained. Unsaved editor amounts are not sent as confirmed settings.

## Optional planning

One **More planning options** selector renders only the selected workflow:

| Option | Interaction |
| --- | --- |
| Fixed amounts | Select categories to keep fixed; preview and confirm. No optimizer setup is required. |
| Savings goals | Select one owned SGD goal and a contribution from the savings pool, or stop its allocation. Other goals/debts/minimums are preserved. |
| Check until payday | Enter dated available cash and add one bill/payday at a time. Preview and confirm. Inspect recorded/scheduled cash flow; remaining category spending and savings timing are optional additional assumptions. |
| Upcoming expenses | Add/edit/remove one reserve with target, already-reserved amount, dates and chosen monthly contribution. A calculated contribution is a suggestion only. Other reserves are preserved. |
| Budgeting methods | Optional method guidance and advanced comparisons, retaining all six methods. |
| Spending patterns | On-demand repeated-overrun evidence; suggestions require review and a confirmed plan change. |
| Previous versions | Inspect history and confirm restoration against current restrictions. |
| Review reminders | Opt-in in-app preferences; no external messages. |
| Plan several months | Advanced batch previews and selected carry rules. |
| Debt repayment comparisons | Specialist illustrations requiring explicit rates, fees and repayment assumptions. |

Payment matching is available only inside the payday workflow. Selecting an expense or income record determines its payment/receipt effect from its stored type; the match still needs an explicit occurrence, amount and confirmation. Refunds ask two plain-language questions about the remaining obligation and recorded spending. These questions are absent for ordinary payments/receipts. IDs remain internal selection values rather than visible labels. Match candidates are never applied automatically.

## Coach reasoning and validation

The authenticated backend builds request-scoped context. Ordinary planning omits unrelated reconciliation records, history and specialist settings. Explicit workspace requests and pending-operation follow-ups receive relevant saved settings and references. The full context remains available to UI workspace APIs and evidence checks.

The selected month is supplied as explicit UI context; a month named in the message takes precedence. The matching owned plan supplies confirmed income, savings, category amounts, computed affordability and aggregate saved restrictions. A different month's plan or unclassified profile income cannot supply confirmed take-home income.

Ordinary requests use a smaller extraction schema without the specialist workspace payload. The agent's deterministic planner includes preserved saved categories and computes requested scenario figures for reasoning. Backend recomputation remains authoritative. Specialist commands retain their existing contract and precise collection edits.

Read-only comparisons no longer require expense-coverage approval. They disclose missing calculation inputs and conflicts with saved restrictions; saving/adoption still requires actual-income and expense-coverage confirmation. A simple savings/income comparison does not require a commitments policy or permission to choose cuts. Without a configured reduction policy, the backend preserves category amounts and asks which can change when there is a gap.

Allocation policies now distinguish absent savings/reduction restrictions (`null`) from an explicit zero. Users can protect a category or fund a goal without configuring every policy field. Existing policies retain their meaning; omitted settings and unrelated collection items remain intact. No migration is needed.

Editing a goal or floor preserves the reference amounts behind an unchanged reduction policy. Newly protected categories freeze their current saved amounts; changing the reduction percentage explicitly establishes a new reference.

For one comparison alternative, **use this change** or **use this option** adopts it as an unsaved draft. With multiple alternatives, Coach asks which one. Adoption and final confirmation remain separate, and expired or changed evidence cannot be bypassed.

## Retained limits and verification

Monthly affordability does not establish a bank balance or liquidity before payday. Payday projections require explicit cash/bill/date information; full category timing additionally requires spending/savings assumptions and record-coverage confirmation. Saved balances, schedules, debt terms, goal allocations and refunds are never inferred from their absence.

Relational reconciliation, account balances/transfers and imports remain excluded as requested. JSON reconciliation, ownership checks, shared savings constraints, cancellation, expiry, atomic persistence and stale-preview rejection remain in force.

Regression coverage checks no-setup comparisons, partial fixed-amount policies, preserved floors, owned context, matching-month reuse, ambiguous adoption, drafts versus saves, simpler UI inputs, stale comparison/copy inputs and conditional refund questions. Offline tests validate deterministic behavior and contracts; they do not establish production natural-language quality. The previous AWS release deployed `c1bb993`; the subsequent routing correction's release was blocked by the container scan. This simplification has not been deployed or live-model accepted.

Local verification: backend **601 passed**, frontend **85 passed**, AI service **1,162 passed** with one existing Windows symlink test unable to run (`WinError 1314`). The focused final AI checks passed 24 tests, and the final simple-flow/matching checks passed seven tests. Ruff, diff whitespace checks and Bandit with the repository's CI severity/confidence thresholds passed. Linux CI must run the symlink case; these counts are local evidence, not a deployed acceptance result.
