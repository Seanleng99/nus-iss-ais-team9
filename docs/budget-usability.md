# Everyday Budget and Coach workflow

Budget provides saved-spending monitoring, charts and a monthly editor. Coach provides guided comparisons and advanced planning commands. This guide describes the current UI; [Budget planning](budget-planning.md) defines the calculation, ownership and confirmation contracts. The [retained browser acceptance](budget-browser-acceptance-20261001.md) applies to its recorded revision. Browser checks and release smoke do not establish current live-model answer quality.

## Everyday Budget page

Saved budgets open with **Spending this month**: **Budgeted / Spent / Remaining**
(or **Over budget**), overall usage and the charts below. **Edit budget** opens the
monthly editor immediately; saved spending and charts remain visible below it. A month without a saved budget opens setup directly.
The selected month remains shared with Overview and supplies Coach's default when the message does not specify a period. Coach can also use explicitly requested months, ranges, years or all saved budgets.

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

## Coach budget management

Coach's caption reads **Default month: October 2026** (using the actual selection). Its help text explains that the selection is used only when the question omits a period. The former "Budget capacity uses the selected month" wording is removed.

Ask Coach to show saved budgets, compare months or summarise a year without changing data. To change saved limits over several months, remove a category, or delete a monthly budget, name the period and requested change. Coach shows the exact before/after values for every affected month. Reply `confirm budget` to apply the whole batch, provide corrections for another preview, or `cancel`. Missing target budgets, invalid allocations and saved commitments block the batch instead of silently skipping months.

Changing limits preserves each month's other categories, income, savings and method. Removing limits keeps recorded transactions. Deleting a monthly budget keeps transactions, goals, bills, reserves and commitment settings, and retains a restorable budget-history version. Delete requests cannot bypass saved commitments. Deleted plans no longer provide confirmed savings capacity.

Explicit months also determine the saved savings pool used in goal calculations. For a requested range, Coach assesses each month separately; a yearly savings total is never treated as one recurring monthly pool. Missing planning settings remain unavailable. Contract regressions cover these workflows. Deployment evidence applies to its recorded revision; complete current live-provider acceptance remains outstanding.

Ordinary advice such as “Which parts of my November budget could I adjust?” receives that month's saved category limits and protected commitments. Spending evidence follows the same period, with prior history identified separately even when the selected month has no transactions. General questions such as “Explain how to calculate disposable income” do not require personal income. If there is no confirmed plan, recurring expenses need known schedules before Coach estimates capacity; historical repeated payments are not summed as separate monthly bills. See [everyday reasoning contracts](budget-planning.md#everyday-reasoning-context).

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

## Retained limits

Monthly affordability does not establish a bank balance or liquidity before payday. Payday projections require explicit cash/bill/date information; full category timing additionally requires spending/savings assumptions and record-coverage confirmation. Saved balances, schedules, debt terms, goal allocations and refunds are never inferred from their absence.

Relational reconciliation, account balances/transfers and imports remain excluded as requested. JSON reconciliation, ownership checks, shared savings constraints, cancellation, expiry, atomic persistence and stale-preview rejection remain in force.

## Verification and limits

Current frontend regressions cover monitoring, editing, cancellation, custom categories, six methods, explicit zero amounts, save-confirmation invalidation, backend rejection and charts based on saved data. Backend/AI suites cover owned previews, capacity sourcing, constraints, comparisons, expiry and atomic writes. See [test organization](test-organization.md) for current required suites and [post-deployment acceptance](post-deployment-acceptance.md) for the optional deployed agent/RAG matrix.

The [retained browser acceptance](budget-browser-acceptance-20261001.md) records its tested UI revision. It does not validate later model extraction or current semantic quality. The [latest live reasoning retest](agent-reasoning-live-test-results-2026-10-09-post7356713.md) retains failed and inconsistent Budget combinations; complete current model acceptance remains outstanding.
