# Everyday Budget and Coach workflow

The simplified Budget page, inline method selector and monthly-editor improvements were tested in the deployed application using the signed-in Edge browser on 2026-10-01. The latest monitoring/editor and always-visible chart changes were subsequently deployed and checked in the same signed-in browser; see [deployed acceptance results](budget-browser-acceptance-20261001.md). Earlier local-only status and test counts below describe each revision before that acceptance run. This document supersedes earlier UI entry points in `budget-planning.md`; calculation and confirmation contracts remain in force. Browser UI checks and release smoke tests do not establish full Budget live-model acceptance.

## Everyday Budget page

Saved budgets open with **Spending this month**: **Budgeted / Spent / Remaining**
(or **Over budget**), overall usage and the charts below. **Edit budget** opens the
monthly editor immediately; saved spending and charts remain visible below it. A month without a saved budget opens setup directly.
The selected month remains shared with Overview and Coach.

- The **Category spending** bar chart compares saved limits with recorded expenses and labels the amounts directly. Over-limit categories appear first in red and their overage amounts are called out above the chart. Spending without limits is shown in amber with no invented budgeted amount. Zero limits are labeled explicitly. Per-category progress cards are removed; the overall budget-used bar remains. Editing a limit does not change saved spending or either chart until saving succeeds.
- **Category spending** and **Budget allocation** are always visible when their data is available, side by side on desktop and stacked on narrow screens. There are no chart switches or chart expanders. Allocation shows the share of saved expense limits; savings are separate. Empty data gets an explanation instead of a misleading chart. Pace details, automatic adjustments and month-copy controls remain removed.
- Category-only tracking remains available without income. **Include take-home income and savings** enables planning; missing amounts remain blank and zero must be entered explicitly. Existing confirmed settings, methods and restrictions are preserved.
- The editor retains six budgeting methods: Flexible category plan, 50/30/20, 80/20, Zero-based, Savings first and Custom percentages. Only Custom shows percentage inputs; they must total 100%. Only 50/30/20 and Custom require one explicit Needs/Wants type per category. **How this method works** contains the explanation, guidance and optional savings-fill action. Guidance never silently changes amounts.
- **Category to add → Add category** offers suggested categories. Selecting **Custom category** reveals a separate name field; no multiselect or Enter-to-create instruction is needed. Names are normalized, limited to 64 characters and checked for duplicates. New limits start blank. Each row has a **Remove [category]** action. Removing a limit keeps transactions and is included in the save review. The 50-category limit has a visible explanation.
- An **Unsaved changes** banner distinguishes edited amounts from the saved plan. **Cancel changes** clears editor inputs, added/removed categories, comparison drafts and confirmation, then returns to saved spending. Reopening restores the saved values. For a new month, cancellation resets the blank setup.
- The editor has a live **Income / Expenses / Savings / Left to allocate** summary. A negative allocation displays **Shortfall** and a correction. Missing amounts remain missing rather than zero. The exact Saved → This plan review covers amounts, category removals, methods, types and percentages before one confirmation and **Save budget**. Any edit changes the confirmation signature and requires fresh approval.
- Missing limits, income, savings and category types are explained beside their controls. Reasons for an unavailable save also appear near the button: incomplete inputs, an empty category list, invalid method percentages, a shortfall or no changes to save. Backend rejections retain inputs and require renewed confirmation. Success returns to saved spending with month-specific confirmation that remains visible across reruns.
- **Explore a change** is removed. Direct editing already shows the effect on monthly affordability before saving. Ask Coach for comparisons or tradeoffs; the deterministic comparison tools and their separate adoption/confirmation contract remain available there.
- Overview offers **View budget** for saved plans and **Set up budget** when no category limits exist. View budget opens monitoring; **Edit budget** starts editing on Budget. The duplicate **Ask Coach** button is removed from Budget. Coach remains available in the sidebar with the shared selected month and saved-plan context; unsaved editor values are not treated as confirmed settings.

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

## Further simplification — 1 October 2026

Next-month copying, category/pace details and suggested adjustments are removed
from Budget. The unused review renderer and copy form are deleted. Budget keeps
the monthly editor, method choices, saved-plan spending summary, category overage
warnings, main chart, optional allocation chart, explicit one-change comparisons
and Coach navigation. The earlier copy-preview browser fix above is historical;
its backend warning correction remains, but the copy UI is no longer offered.

Ordinary Coach reviews still use deterministic, owned SGD spending and optional
bounded pace calculations. Reviews no longer create a **Cover recorded spending**
scenario or suggest raising limits to recorded expenses. An overage is evidence
to discuss, not permission to normalize overspending. Coach can clarify whether
purchases repeat and ask which amount the user wants to compare before calling
the existing comparison tools. Adoption produces an unsaved draft and saving
still requires confirmation of actual income, expense coverage and the changes.
Explicit requests to reuse a month can still use the backend preview/confirmation
contract; no recurring copy or automatic rollover is added.

Review responses use `budget-review-v2`; compatibility fields `suggestions` and
`comparison` are empty/null. Existing saved plans and transactions are unchanged.
Legacy pending review-derived drafts retain their evidence checks at adoption,
clarification and final save. No database migration is needed. These changes and
the earlier browser fixes remain local until explicitly pushed for deployment.

Verification: the full frontend suite passed **95 tests**; focused backend review,
method, planning, capture and continuity suites passed **74 tests**; focused AI
review, method, planner and capture suites passed **25 tests**. Ruff and diff
whitespace checks passed. These are offline checks; the simplified page has not
yet been deployed or retested against the live model.

## Monitoring and editor layout — 1 October 2026

This revision separates saved spending from editing. The previous always-visible
form and category multiselect are replaced by monitoring mode, explicit editing,
row removal and an Add category action. This earlier revision collapsed chart and method guidance views;
the always-visible chart revision below supersedes its chart behavior. On narrow screens, monitoring metrics use two columns with Remaining
on its own row; the editor summary uses a two-by-two layout. Amount inputs and
category types retain readable labels and ordinary keyboard controls.

The public Budget entry point delegates to `ui/budget_page.py`;
`ui/budget_spending.py` renders saved facts independently of editor state.
Backend APIs, deterministic calculations, ownership and confirmation contracts
are unchanged. No database migration is required. The revision remains local.

The full frontend suite passed **102 tests**, including new checks for monitoring
mode, cancellation, comparison adoption, duplicate/custom category input,
explicit zero amounts, category limits, empty categories, persistent save
feedback and zero-limit/unbudgeted spending. Ruff and diff whitespace checks
passed. A local Edge fixture rendered the actual page with synthetic data and
the repository's light theme. Desktop checks confirmed immediate editor placement,
unsaved status and cancellation; at **390 × 844**, monitoring metrics used two
columns plus a full-width Remaining card, category statuses stayed readable, and
the editor summary used two-by-two cards. Both monitoring and editing had a
390-pixel document width, with no document-level horizontal overflow. Cancellation
restored the saved savings allocation. The fixture did not contact the deployed
backend. Production and live-model acceptance remain separate.

## Always-visible charts — 1 October 2026

The optional **Explore a change** form and its unused frontend renderer are
removed. Coach retains deterministic comparisons and explicit adoption before
confirmation. Budget editing still calculates live affordability and reviews
changes before a confirmed save. Legacy local drafts remain reviewable and
cancellable; whole-number draft limits are converted to the editor's numeric
format while missing values remain unknown.

Both charts appear automatically with meaningful saved data, including below
the editor. Per-category progress cards are removed. The overall progress bar,
headline totals, explicit category overages and spending without limits remain.
The spending chart labels amounts; its unbudgeted row has no invented limit.
The allocation donut shows saved expense shares and category names in a legend.

The full frontend suite passed **101 tests**. After removing the overlapping
chart toolbar, the focused monitoring/editor checks passed **16 tests**. Ruff
and diff whitespace checks passed. Coverage includes automatic chart rendering,
saved limits staying unchanged during edits, unbudgeted spending without an
invented limit, explicit zero limits, no UI comparison/review calls and legacy
draft cancellation.

A local Edge fixture rendered the actual frontend with synthetic data. Desktop
charts appeared side by side; at **390 × 844** they stacked at 348-pixel widths,
with a 390-pixel document width and no page-level horizontal overflow. Category
names, amounts and allocation legend were checked visually. Editing retained
both saved charts; cancelling returned to monitoring. Screenshots are stored
in `artifacts/budget-browser-20261001/charts-desktop.jpg`, `charts-mobile.jpg`
and `charts-mobile-allocation.jpg`. The fixture did not contact the deployed
backend or run live-model acceptance.

No backend calculation, write contract or migration changes. This revision
is validated locally; deployment and live-model acceptance remain pending.

## Navigation simplification — 1 October 2026

Overview's **Manage budget** shortcut is renamed **View budget** because it opens
Budget monitoring rather than editing. **Set up budget** remains the empty-plan
action. The duplicate **Ask Coach** button and its two-column action layout are
removed from Budget; **Edit budget** remains the monitoring action.

Coach is still accessible through the sidebar. Shared month selection and saved
budget context are unchanged, and unsaved editor amounts are not automatically
sent or saved. The obsolete button-specific test was removed with the button.
The full frontend suite passed **100 tests**; Ruff and diff whitespace checks
passed. These checks validate the revision locally; deployed browser verification
remains pending. The browser acceptance report above records the earlier deployed
shortcut behavior.

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
The Budget page focuses on saved spending, always-visible charts, an explicit
monthly editor. Coach remains accessible through the sidebar. The unused frontend
renderers and their form-specific tests are removed, including the older cash-flow,
reconciliation and full-commitments editors. Backend calculations, saved settings,
workspace APIs and Coach operations remain available; no data or migrations change.

| Removed UI | Reason and supported path |
| --- | --- |
| Fixed amounts | A separate protection setup is unnecessary for normal category editing. Coach preserves category amounts in ordinary comparisons and can save explicitly requested fixed amounts after confirmation. |
| Savings goals | Goal creation and progress already belong on the Goals page. Ask Coach about a monthly contribution if needed; allocation still uses the shared savings pool. |
| Check until payday | Requires separate cash balances, schedules and reconciliation to provide an honest answer. Coach gathers these inputs only when the user asks a timing question; no routine setup is required. |
| Upcoming expenses | Ordinary costs can be entered as custom categories. Coach supports explicit reserve planning where a target and deadline matter. |
| Separate budgeting-method explorer | Replaced by a single inline method selector in Edit budget. Custom inputs appear only when needed; the scenario workspace remains removed. Coach can also explain, compare and change a method. |
| Spending patterns | Category overages remain visible in the main spending summary. Detailed reviews, pace illustrations and historical analysis are available through Coach on request. |
| Previous versions | Version restoration is not a primary monthly budgeting task. Backend history and confirmed restoration remain available to Coach. |
| Review reminders | Recorded spending appears when the Budget page opens; detailed reviews are available through Coach on request. There is no reminder-preferences form on Budget. Existing preferences remain stored. |
| Plan several months | Budget has no copy or multi-month form. Coach retains explicitly requested month reuse, multi-month and carry-rule planning with preview and confirmation. |
| Debt repayment comparisons | Rates, fees and repayment policies need guided clarification. Coach retains deterministic comparisons; Budget does not duplicate a debt-planning interface. |

Sidebar navigation to Coach retains the selected month without sending a
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
