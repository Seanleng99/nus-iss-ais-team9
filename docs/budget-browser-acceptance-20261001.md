# Deployed Budget browser acceptance — 1 October 2026

The deployed Budget page passed the exercised functional and responsive checks
in the user's signed-in Edge tab, controlled through the Browser plugin. One
minor Overview help-text defect was found; the subsequent local correction is
recorded below. No blocking Budget-page issue was observed in these flows.

## Environment and scope

- Site: https://ai-financial-wellness-coach.click/
- Profile: **Budget UI Test — synthetic** (`budget-ui-test-20261001`).
- Saved month: October 2026. Empty setup: December 2026.
- Desktop viewport: 1528 pixels wide. Mobile check: 390 × 844.
- All interactions used the rendered application; no direct API calls or local
  frontend fixture supplied the test results.

Starting October plan: income SGD 5,000; savings SGD 1,000; Custom percentages
60/20/20; Food 600, Housing 1,500, Pet Care 100, Transport 200 and Utilities 200,
all explicitly classified as Needs. Total limits were SGD 2,600. Recorded
spending was SGD 750: Food 650 and SGD 100 without category limits.

## Exercised checks

| Check | Result and observed behavior |
| --- | --- |
| Saved-budget landing | Pass. Monitoring opens first; Edit budget opens the editor immediately. No initial amount inputs. |
| Charts always visible | Pass. Category spending and allocation both render automatically, side by side on desktop and stacked on mobile. No chart switches or chart expander. |
| Removed controls | Pass. No Explore a change, category progress cards, next-month copy, pace or adjustment controls on Budget. One overall usage bar remains. |
| Spending and warnings | Pass. Budgeted 2,600, Spent 750, Remaining 1,850; Food is 50 over its category limit. Spending without limits is called out as 100 and appears separately in the chart. |
| Saved figures during editing | Pass. A savings change and Food 600 → 610 changed editor affordability; saved totals and both charts retained the original amounts. |
| Affordability | Pass. Savings 3,000 produced a 600 shortfall and disabled saving. Savings 1,100 produced 1,300 left to allocate. |
| Confirmation | Pass. Save without confirmation displayed the review warning. Checking confirmation and then changing Food cleared the approval. |
| Duplicate custom category | Pass. `  FOOD  ` was rejected as already present. No duplicate row was created. |
| Unknown custom inputs | Pass. `  Live UI   QA 20261001  ` normalized to one category with a blank limit and unselected type. Missing values disabled saving; no amount or type was inferred. |
| Explicit zero and type | Pass. Entering 0 and selecting Wants completed that category. The review showed Not set → SGD 0.00 and the explicit type. |
| Cancellation | Pass. Cancel discarded edited amounts, an added custom category, an unsaved Pet Care removal and confirmation. Reopening restored the original five categories and saved amounts. |
| Method choices | Pass. Switched among Flexible category plan, 50/30/20, 80/20, Zero-based, Savings first and Custom percentages. Entered income, savings and limits remained intact. Grouping and percentage fields appeared only when relevant. |
| Method validation | Pass. Zero-based blocked saving with 1,400 unallocated. A 60/20/10 custom split showed a 90% total and blocked saving. Returning to 60/20/20 restored valid guidance. |
| Confirmed save and reload | Pass. Saved the synthetic zero-limit category with Wants and savings 1,100. Success returned to monitoring. Reload and reopening retained the category, amount, type, savings and custom split. |
| Restoration | Pass. Reviewed removal of only the temporary test category and savings 1,100 → 1,000; confirmed the restoration. Reload showed the starting plan and unchanged spending totals. |
| Empty-month setup | Pass. December had blank limits and no inherited saved income/savings. Enabling planning produced blank income and savings inputs. Cancel reset setup; no December budget was saved. |
| Coach shortcut | Pass. Ask Coach opened Coach with October 2026 selected and the matching budget-capacity caption. No chat message was submitted. |
| Overview consistency | Pass for amounts and warnings. Overview showed the same restored method, income, savings, unallocated amount, totals, Food overage and unbudgeted spending. Its help text has the defect below. |
| Responsive layout | Pass. At 390 × 844, document width remained 390. Both charts were 348 pixels wide. Monitoring metrics used two columns and full-width Remaining; editor metrics used two rows of two cards. No page-wide horizontal overflow was observed. |

Clearing an existing populated Food input reverted to its saved value of 600;
it did not become an assumed zero. Missing-input checks were exercised using
new custom-category and empty-month inputs.

## Remaining finding

**Minor: stale help text in Overview's Budget section.**

The deployed section says “Open Budget for recorded-spending reviews and pace
illustrations.” Budget no longer exposes those features; Coach retains them on
request. Update the caption to direct category editing to Budget and reviews to
Coach. The source is `apps/frontend/ui/pages.py:510`. This test did not change
application code to fix the caption.

### Local correction after acceptance

Overview now says: “Edit your plan in Budget. Ask Coach for spending reviews or
pace illustrations.” The correction changes only the caption; navigation and
budget calculations are unchanged. All **11 Overview tests** passed; Ruff and
diff whitespace checks passed. The corrected caption has not been pushed or
verified in the deployed browser.

## Evidence and cleanup

Screenshots are stored locally under `artifacts/budget-live-20261001/`:

- `monitoring-desktop.jpg`: deployed charts before the save tests.
- `monitoring-mobile.jpg`: mobile spending chart and stacked allocation.
- `editor-mobile.jpg`: editor summary and amount inputs at 390 × 844.
- `overview-help-issue.jpg`: stale Overview help text and matching plan amounts.
- `restored-budget-desktop.jpg`: final restored plan after reload.

The temporary category was removed through reviewed, confirmed budget editing.
October's original plan was restored; the recorded expenses were unchanged.
December was not saved. The viewport override was reset and the user's existing
tab was left on Budget with October selected. No other profile was edited.

These are deployed UI acceptance results, not full live-model acceptance. Coach
reasoning, scenario adoption, stale-evidence rejection, backend ownership tests,
service outages and concurrent saves were not exercised in this browser run.
