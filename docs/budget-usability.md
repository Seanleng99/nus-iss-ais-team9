# Everyday Budget and Coach workflow

The simplified Budget page, inline method selector and monthly-editor improvements were tested in the deployed application using the signed-in Edge browser on 2026-10-01. The browser findings and their subsequent local fixes are described below. The fixes have not been deployed. This document supersedes earlier UI entry points in `budget-planning.md`; calculation and confirmation contracts remain in force. Browser UI checks and release smoke tests do not establish full Budget live-model acceptance.

## Everyday Budget page

The page starts with **Your plan** and a live **Income / Expenses / Savings / Left to allocate** summary, followed by **Spending this month** and **Explore a change**. A negative allocation displays a positive **Shortfall** and a plain-language correction. Missing amounts are labeled as missing rather than treated as zero; the allocation is not a bank balance.

- Category-only tracking remains available without income. New category amounts start blank; zero must be entered explicitly.
- **Include take-home income and savings** creates a planned budget directly in the main editor. Both amounts start blank for new plans. Existing confirmed settings are preserved, including the chosen method.
- **Budgeting method** is one inline dropdown: Flexible category plan, 50/30/20, 80/20, Zero-based, Savings first or Custom percentages. Existing plans select their saved method; new plans start Flexible. A brief explanation and income-based guidance appear without changing any entered amounts.
- Only Custom percentages shows three percentage inputs; they start blank unless saved and must total 100%. Only 50/30/20 and Custom show a Needs/Wants selector beside each category amount. Each category has one explicit type; missing types prevent saving. No duplicate-group selection is possible. Zero-based plans must assign all income to expenses or savings. Any change to income, savings, categories, category types, limits or method details requires fresh confirmation; changed comparison inputs hide obsolete results.
- The editor uses ordinary editable rows, with full-width amount fields for methods that do not need category types. Custom categories are still added by typing a name in Budget categories and pressing Enter. A short Saved → This plan table highlights changes, additions, removals, types and custom percentages before one confirmation and Save budget. Category-only plans also require review confirmation. Larger change lists expose a full review. Removing a limit preserves transactions and explains that they become unbudgeted spending. Saving still checks affordability, method requirements and saved restrictions in the backend.
- Recorded spending reviews load automatically and can be refreshed. Budget and Overview use the same all-category recorded spending totals, including expenses without limits, for Spent, Remaining/Over budget and overall usage. Category warnings and charts still compare each saved limit with its own expenses. Currency appears in the chart caption and the legend sits above the bars. The allocation chart, review totals and category/pace details are opt-in. Recorded totals and unbudgeted spending remain visible. Adjustment proposals are optional. Reviews stay read-only; an adjustment fills an unsaved editor draft and needs confirmation before saving. Cached reviews are invalidated when the saved budget/spending response or Singapore date changes.
- **Explore a change** changes one income, savings or category amount. Users do not need to choose a budgeting method, provide three income cases or name a scenario. A compact Current → Proposed table shows income, expenses, savings, left to allocate, shortfall and the selected category amount if relevant. Current means the editor amounts, including unsaved edits. Results disclose shortfalls and saved restrictions. Adopting a result changes only the unsaved editor; changing comparison inputs hides obsolete results.
- **Use this plan next month** previews a copy of saved limits with explicitly reviewed income and savings. It requires expense-coverage confirmation, detects existing target plans and requires explicit overwrite permission. Changing inputs hides the old preview and requires fresh confirmation for the revised amounts. Simple copies omit unrelated rollover and override explanations. Relevant saved-commitment questions and replacement warnings remain visible. Multi-month and surplus/net carry calculations are available through Coach rather than a separate Budget form; their preview explanations appear only when applicable.
- **Discuss my saved budget with Coach** opens Coach with the selected month retained. Unsaved editor amounts are not sent as confirmed settings.

## Browser acceptance follow-up — 1 October 2026

The deployed Edge session exercised missing-input validation, save confirmation,
all six method choices, custom percentages and categories, reload persistence,
affordable and unaffordable comparisons, spending/adjustment reviews, next-month
copying, Overview and Coach navigation. It used an isolated synthetic profile,
two monthly plans and two labelled transactions. A 390 × 844 viewport was also
checked. No live Coach message was sent.

Four issues were reproduced and fixed locally:

1. Overview no longer claims the monthly total is exceeded solely because a
   category is over its limit. For spending of SGD 750 against SGD 2,600 in total
   limits, with Food at SGD 650 against a SGD 600 limit, it reports Food's SGD 50
   category overage. Total-budget and income-overrun warnings still apply when
   those totals are actually exceeded.
2. Budget now includes unbudgeted expenses in its headline figures, as Overview
   already does. With SGD 650 in Food and SGD 100 in unbudgeted Entertainment,
   both pages show Spent SGD 750 and Remaining SGD 1,850. An adjacent caption
   identifies spending without category limits. Unsaved editor changes do not
   affect the saved-plan spending summary.
3. A simple one-month copy shows the target month, copied limits, supplied income
   and savings, and confirmation. The backend returns carry and multi-month
   explanations only for those operations. Existing-plan replacement and relevant
   saved-commitment warnings/questions remain visible; enforcement is unchanged.
4. The primary spending chart's legend now sits above the bars. Its currency is
   shown in a caption instead of an axis title that overlapped the mobile legend.

Local verification passed **97 frontend tests** and **11 backend continuity
tests**, with Ruff and whitespace checks. A separate local Edge fixture rendered
the actual frontend code with the same synthetic totals: the corrected Overview
warning, matching spending totals and mobile chart were verified visually. At
390 × 844 the chart's labels were separated and no document-level horizontal
overflow was observed. The fixture did not contact the deployed backend, so this
does not claim the fixes are live or that the live model has been retested.

## Guidance and save feedback

Percentage methods show a small Suggested / Your plan table using full take-home
income, including the custom split. Unknown group amounts remain labeled as
incomplete. **Use suggested savings amount** is an explicit optional action for
50/30/20, 80/20 and valid custom splits; it fills only the savings field, leaves
category limits unchanged and requires renewed confirmation before saving.
Savings first uses the user-chosen amount; Flexible and Zero-based do not invent
a savings percentage.

Local input errors identify the missing category or financial input and keep the
rest of the page available. Backend validation errors surface the corrective
message without echoing rejected payloads; inputs remain in the editor and a
rejected save requires confirmation again. HTTP/service failures continue to use
the shared error handling. No method selection, suggested amount or comparison
adoption saves a budget automatically.

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

Regression coverage checks no-setup comparisons, partial fixed-amount policies, preserved floors, owned context, matching-month reuse, ambiguous adoption, drafts versus saves, simpler UI inputs, stale comparison/copy inputs and conditional refund questions. Offline tests validate deterministic behavior and contracts; they do not establish production natural-language quality. The first simplification and routing correction were deployed at `72846d0` after explicitly approved exact-package security exceptions. [Release run 36805858272](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36805858272) passed scans, migrations, all three service deployments and health/AI safety smoke tests. The later UI improvements were subsequently checked in the deployed browser session described above; full live-model acceptance remains pending.

Verification of the first simplification before optional-form removal: backend **601 passed**, frontend **85 passed**, AI service **1,162 passed** with one existing Windows symlink test unable to run (`WinError 1314`). The focused final AI checks passed 24 tests, and the final simple-flow/matching checks passed seven tests. Ruff, diff whitespace checks and Bandit with the repository's CI severity/confidence thresholds passed. Linux CI must run the symlink case; these counts are local evidence, not a deployed acceptance result.

Verification of the optional-form removal: the full remaining frontend suite
passed **76 tests**, including comparison adoption, saved-method preservation,
save confirmation, next-month preview invalidation, Overview and Coach navigation.
Frontend Ruff and diff whitespace checks passed. Tests specific to deleted forms
were removed with those forms. Backend/AI code and their confirmation contracts
were not modified by this revision; their earlier test counts above are historical
evidence rather than newly executed suites.

Before deployment, the inline method selector's focused checks passed
13 tests, including explicit custom percentages/grouping, all six methods,
no automatic amount changes, zero-based completeness, and fresh confirmation
after method changes. Deployment and full-suite results are recorded separately.

The full frontend suite for this revision passed **83 tests**, and the backend
method suite passed **19 tests**. Frontend Ruff and diff whitespace checks passed.
These counts are historical pre-deployment evidence; live-model acceptance
remains separate.

The monthly-editor layout, compact charts, guided savings and save-review revision's
interaction checks cover missing custom amounts,
confirmation invalidation after edits, explicit category removal, suggested savings,
comparison values and rejected-save input retention. Automated checks verify
behavior; they do not establish mobile visual usability or live-model quality.

Verification for the monthly-editor revision: the full frontend suite passed
**89 tests**, including the six new editor interaction checks. The unchanged
backend method suite passed **19 tests**. Frontend Ruff and diff whitespace checks
passed. At that stage the headless browser library was unavailable. The subsequent
Edge desktop/mobile visual checks are recorded above; no user usability study is claimed.
