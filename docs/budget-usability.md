# Everyday Budget and Coach workflow

The first simplification was deployed on 2026-10-01 at `72846d0` and passed release health and AI safety smoke tests. The further removal of optional planning forms described below is implemented locally and has not been deployed. This document supersedes earlier UI entry points in `budget-planning.md`; calculation and confirmation contracts remain in force. Release smoke tests do not establish full Budget live-model acceptance.

## Everyday Budget page

The page starts with **Your plan**, followed by **Spending this month** and **Explore a change**.

- Category-only tracking remains available without income. New category amounts start blank; zero must be entered explicitly.
- **Include take-home income and savings** creates a planned budget directly in the main editor. Both amounts start blank for new plans. Existing confirmed settings are preserved, including the chosen method.
- **Budgeting method** is one inline dropdown: Flexible category plan, 50/30/20, 80/20, Zero-based, Savings first or Custom percentages. Existing plans select their saved method; new plans start Flexible. A brief explanation and income-based guidance appear without changing any entered amounts.
- Only Custom percentages shows three percentage inputs; they start blank unless saved and must total 100%. Only 50/30/20 and Custom show needs/wants grouping. Users choose each category's group explicitly; missing or duplicate groups prevent saving. Zero-based plans must assign all income to expenses or savings. Changing the method or its details requires a fresh confirmation and hides obsolete comparison results.
- The editor updates planned expenses, savings and unallocated income/shortfall as amounts change. One confirmation states that the income is actual take-home income and the limits include all expenses. Saving still checks affordability, method requirements and saved restrictions in the backend.
- Recorded spending reviews load automatically and can be refreshed. Category/pace details and adjustment proposals are optional. Reviews stay read-only; an adjustment fills an unsaved editor draft and needs confirmation before saving. Cached reviews are invalidated when the saved budget/spending response or Singapore date changes.
- **Explore a change** changes one income, savings or category amount. Users do not need to choose a budgeting method, provide three income cases or name a scenario. Results disclose shortfalls and saved restrictions. Adopting a result changes only the unsaved editor; changing comparison inputs hides obsolete results.
- **Use this plan next month** previews a copy of saved limits with explicitly reviewed income and savings. It requires expense-coverage confirmation, detects existing target plans and requires explicit overwrite permission. Changing inputs hides the old preview. Multi-month and surplus/net carry calculations are available through Coach rather than a separate Budget form.
- **Discuss my saved budget with Coach** opens Coach with the selected month retained. Unsaved editor amounts are not sent as confirmed settings.

## Removal of optional planning forms

The **More planning options** menu and all ten standalone workflows are removed.
The Budget page focuses on the monthly plan, recorded spending, one-change
comparisons, next-month copying and the Coach shortcut. The unused frontend
renderers and their form-specific tests are removed, including the older cash-flow,
reconciliation and full-commitments editors. Backend calculations, saved settings,
workspace APIs and Coach operations remain available; no data or migrations change.

| Removed UI | Reason and supported path |
| --- | --- |
| Fixed amounts | A separate protection setup is unnecessary for normal category editing. Coach preserves category amounts in ordinary comparisons and can save explicitly requested fixed amounts after confirmation. |
| Savings goals | Goal creation and progress already belong on the Goals page. Ask Coach about a monthly contribution if needed; allocation still uses the shared savings pool. |
| Check until payday | Requires separate cash balances, schedules and reconciliation to provide an honest answer. Coach gathers these inputs only when the user asks a timing question; no routine setup is required. |
| Upcoming expenses | Ordinary costs can be entered as custom categories. Coach supports explicit reserve planning where a target and deadline matter. |
| Separate budgeting-method explorer | Replaced by a single inline method selector in Your plan. Custom inputs appear only when needed; the scenario workspace remains removed. Coach can also explain, compare and change a method. |
| Spending patterns | The automatic spending review already shows warnings and adjustment proposals. Historical analysis remains an on-demand Coach capability. |
| Previous versions | Version restoration is not a primary monthly budgeting task. Backend history and confirmed restoration remain available to Coach. |
| Review reminders | Spending reviews already load when the Budget page opens. There is no reminder-preferences form on Budget. Existing preferences remain stored. |
| Plan several months | One-click next-month copying covers the everyday need. Coach retains explicit multi-month and carry-rule planning. |
| Debt repayment comparisons | Rates, fees and repayment policies need guided clarification. Coach retains deterministic comparisons; Budget does not duplicate a debt-planning interface. |

The Coach shortcut retains the selected month and navigates without sending a
message or treating unsaved editor amounts as confirmed. A short caption provides
examples of requests instead of replacing the removed menu with another setup
screen. Payment matching is no longer exposed on Budget; owned JSON matching
and its confirmation/financial-effect contracts remain in the backend and Coach.

## Coach reasoning and validation

The authenticated backend builds request-scoped context. Ordinary planning omits unrelated reconciliation records, history and specialist settings. Explicit workspace requests and pending-operation follow-ups receive relevant saved settings and references. The full context remains available to UI workspace APIs and evidence checks.

The selected month is supplied as explicit UI context; a month named in the message takes precedence. The matching owned plan supplies confirmed income, savings, category amounts, computed affordability and aggregate saved restrictions. A different month's plan or unclassified profile income cannot supply confirmed take-home income.

Ordinary requests use a smaller extraction schema without the specialist workspace payload. The agent's deterministic planner includes preserved saved categories and computes requested scenario figures for reasoning. Backend recomputation remains authoritative. Specialist commands retain their existing contract and precise collection edits through Coach; they do not require dedicated Budget forms.

Read-only comparisons no longer require expense-coverage approval. They disclose missing calculation inputs and conflicts with saved restrictions; saving/adoption still requires actual-income and expense-coverage confirmation. A simple savings/income comparison does not require a commitments policy or permission to choose cuts. Without a configured reduction policy, the backend preserves category amounts and asks which can change when there is a gap.

Allocation policies now distinguish absent savings/reduction restrictions (`null`) from an explicit zero. Users can protect a category or fund a goal without configuring every policy field. Existing policies retain their meaning; omitted settings and unrelated collection items remain intact. No migration is needed.

Editing a goal or floor preserves the reference amounts behind an unchanged reduction policy. Newly protected categories freeze their current saved amounts; changing the reduction percentage explicitly establishes a new reference.

For one comparison alternative, **use this change** or **use this option** adopts it as an unsaved draft. With multiple alternatives, Coach asks which one. Adoption and final confirmation remain separate, and expired or changed evidence cannot be bypassed.

## Retained limits and verification

Monthly affordability does not establish a bank balance or liquidity before payday. Payday projections require explicit cash/bill/date information; full category timing additionally requires spending/savings assumptions and record-coverage confirmation. Saved balances, schedules, debt terms, goal allocations and refunds are never inferred from their absence.

Relational reconciliation, account balances/transfers and imports remain excluded as requested. JSON reconciliation, ownership checks, shared savings constraints, cancellation, expiry, atomic persistence and stale-preview rejection remain in force.

Regression coverage checks no-setup comparisons, partial fixed-amount policies, preserved floors, owned context, matching-month reuse, ambiguous adoption, drafts versus saves, simpler UI inputs, stale comparison/copy inputs and conditional refund questions. Offline tests validate deterministic behavior and contracts; they do not establish production natural-language quality. The first simplification and routing correction were subsequently deployed at `72846d0` after explicitly approved exact-package security exceptions. [Release run 36805858272](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36805858272) passed scans, migrations, all three service deployments and health/AI safety smoke tests. The current optional-form removal has not been deployed or live-model accepted.

Verification of the first simplification before optional-form removal: backend **601 passed**, frontend **85 passed**, AI service **1,162 passed** with one existing Windows symlink test unable to run (`WinError 1314`). The focused final AI checks passed 24 tests, and the final simple-flow/matching checks passed seven tests. Ruff, diff whitespace checks and Bandit with the repository's CI severity/confidence thresholds passed. Linux CI must run the symlink case; these counts are local evidence, not a deployed acceptance result.

Verification of the optional-form removal: the full remaining frontend suite
passed **76 tests**, including comparison adoption, saved-method preservation,
save confirmation, next-month preview invalidation, Overview and Coach navigation.
Frontend Ruff and diff whitespace checks passed. Tests specific to deleted forms
were removed with those forms. Backend/AI code and their confirmation contracts
were not modified by this revision; their earlier test counts above are historical
evidence rather than newly executed suites.

The inline method selector is a further local revision. Its focused checks passed
13 tests, including explicit custom percentages/grouping, all six methods,
no automatic amount changes, zero-based completeness, and fresh confirmation
after method changes. Deployment and full-suite results are recorded separately.

The full frontend suite for this revision passed **83 tests**, and the backend
method suite passed **19 tests**. Frontend Ruff and diff whitespace checks passed.
The inline selector is committed locally and has not been deployed or validated
with the live model.
