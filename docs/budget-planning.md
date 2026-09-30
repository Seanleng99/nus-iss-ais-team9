# Budget planning: plans, methods, scenarios and spending reviews

Status: deployed to the AWS demo on 2026-09-29 at `f821887a62e8b8d94aa77975f34d6770042e6312`. CI, migrations and release smoke passed. The focused GPT-6 Luna Budget acceptance suite passed 14/14 executions; see the deployed verification record below.

## User workflow

Ask Coach: **“Help me create a realistic monthly budget.”** The orchestrator routes planning requests to Budget. Existing requests to record explicit limits continue to use the capture workflow.

The planner collects:

- The exact month/year and SGD currency.
- Monthly **take-home income**, explicitly supplied or adopted and confirmed by the user. A saved profile income has an unknown take-home/gross basis until confirmed.
- A monthly savings allocation. Zero is valid when explicitly selected; a missing target is not treated as zero.
- Category expense limits, including custom categories. These include essential commitments, debt payments and monthly amounts for irregular expenses where applicable.
- Explicit confirmation that the proposed category limits include all expenses/commitments. The user can reply **“all expenses included”** or supply missing amounts.

Users can supply their own amounts or request **“use recorded spending”** to obtain suggestions. The backend provides SGD category totals for the last three closed calendar months, scoped to the authenticated profile. The deterministic planner selects the latest available month before the requested plan month. Closed calendar periods do **not** establish that records are complete. Every derived category is labeled with its reference month and marked as a suggestion; newly generated suggestions require expense-coverage confirmation.

Explicit category limits take precedence over history. An explicitly named category with an unknown amount remains unresolved. Recorded categories named savings, emergency fund or investments are excluded from expense suggestions to avoid counting a savings allocation twice. Recurring transaction rows are not added separately to category totals, preventing duplicate counting. If records are unavailable, the planner requests amounts instead of inventing them. More than 50 categories requires the user to specify a smaller plan.

The backend presents all proposed changes, preserved existing category limits, and an affordability summary. A valid plan still requires **“confirm budget”** before saving. **“cancel”** discards the pending plan. A yes/no answer to an incomplete planning question is routed back for clarification, rather than treated as save permission or cancellation.

## Deterministic calculations

```text
planned expenses = sum(all category limits in the resulting monthly budget)
allocated income = planned expenses + monthly savings allocation
unallocated income = max(take-home income - allocated income, 0)
funding gap = max(allocated income - take-home income, 0)
```

The checks include existing limits that will be preserved, not just the categories mentioned in the latest message. Decimal arithmetic is used for the backend funding check. Negative/non-finite values, invalid currency, duplicate categories, unsupported precision, and incomplete inputs cannot be confirmed.

A funding gap prevents confirmation and saving. The agent asks which amounts the user wants to revise; it does not automatically cut essential commitments, modify a savings goal, or distribute spare income. A positive unallocated amount is allowed and disclosed. “Affordable” means the supplied plan fits the supplied income, conditional on the user's confirmation of expense coverage; it is not independent verification of the household's finances.

Example: SGD 4,000 income, SGD 3,400 expenses and SGD 800 savings produce a SGD 200 funding gap. After the user reduces expenses to SGD 3,200, the plan balances. Savings are persisted separately and are never counted as an expense category or a recorded savings balance.

## Architecture and contracts

- `apps/ai-service/app/agents/budget_capture.py`: typed extraction contract for user inputs and corrections, versioned as `budget-planning-v3`. The model interprets language; it cannot write budgets.
- `apps/ai-service/app/tools/budget_planner.py`: allowlisted deterministic category proposals, provenance, expense totals and funding gaps. It does not use 50/30/20 to generate a category plan.
- `apps/ai-service/app/orchestrator.py`: `budget_planning` intent, continuity for pending planning drafts, and role-scoped aggregate context. Only planning Budget tasks receive `planning_context`; no raw transaction descriptions are added to this context.
- `apps/backend/app/services/budget_planning.py`: owned SGD aggregate construction, required planning inputs, authoritative affordability arithmetic and explanation.
- `apps/backend/app/services/budget_capture.py`: preview, independent recomputation over the merged plan, explicit confirmation, conflict checking and atomic persistence. Dropping the planning object cannot bypass checks on an existing planning draft.
- `BudgetUpsert.planning` / `BudgetResponse.planning`: nullable `BudgetPlanSettings` containing `take_home_income`, `savings_target`, confirmed `income_basis`, `expenses_confirmed`, and planner `version`. The API validates expenses plus savings against income whenever planning settings are supplied.
- `MonthlyBudgetRecord.planning`: nullable JSON column. Existing budgets remain valid with null planning settings. Planning metadata is included in owner data export and follows the monthly budget's ownership/deletion lifecycle.

Pending drafts use the existing conversation-scoped JSON field. Preview expiry (30 minutes), changed-budget detection, re-confirmation after intervening turns, and atomic budget/draft/chat commits remain in force. Saved plan settings participate in conflict detection. Public Coach requests cannot supply trusted pending drafts or aggregate context.

The Budget and Overview pages show take-home income, the separate savings allocation, and unallocated income for saved plans. The Budget form preserves these settings, requires confirmation of expense coverage when editing, and prevents saving a funding gap. Direct API clients editing a planned budget should round-trip its `planning` settings; this optional field distinguishes a planned budget from a legacy manual category budget.

## Stage two: method selection and scenario comparisons

Users can select a method in Coach or in **Budget → Explore budgeting methods and scenarios**. The method is saved alongside income and savings; Overview displays it. Existing saved v1 plans load as flexible plans. No new database migration is needed beyond `20260929_0011` because the settings use the existing JSON column.

| Method | Behavior |
| --- | --- |
| Flexible category plan | Explicit expense limits and savings; unallocated income is allowed. |
| 50/30/20 | Guidance targets for needs/wants/savings are 50/30/20 percent of **full take-home income**. The user classifies every category. |
| 80/20 | Guidance targets for total expenses/savings are 80/20 percent of full take-home income. |
| Zero-based | Expenses plus savings must equal take-home income exactly before saving. No automatic distribution of unallocated income. |
| Savings first | Reserve the user's chosen savings amount, then compare expenses against the remainder. No default savings percentage. |
| Custom percentages | User supplies needs/wants/savings percentages totaling exactly 100 and classifies every category. |

Percentage targets are advisory: deviations are shown, but an otherwise complete, affordable plan can be saved. The chosen monthly savings amount is never silently replaced by a calculated target. Custom percentages and category classification must be complete before saving. Existing category limits participate in the calculation and classification requirements. All debt payments remain explicit expense categories in this application's simplified model; they are not counted again as savings. This differs from versions of percentage rules that combine savings and additional debt payments. The [CFPB budgeting activity](https://files.consumerfinance.gov/f/documents/cfpb_building_block_activities_analyzing-budgets_guide.pdf) provides the take-home-income needs/wants/savings teaching convention; the other options above describe application behavior, not personalized recommendations.

A **comparison** evaluates the current proposal and up to three named alternatives. An alternative can override monthly take-home income, monthly savings, category amounts, or the method. Missing override fields inherit the base; an explicit zero is retained. Each option is evaluated independently and cannot mutate the base or another option. Results show expenses, savings, unallocated income, funding gaps, changes in unallocated income, method guidance, and unresolved questions. Hypothetical funding gaps are allowed in comparisons and prevent saving a resulting plan. Comparisons do not predict future transactions, returns, or goal completion dates.

Coach examples (production language extraction):

- “Use 50/30/20 for this budget. Housing is a need and hobbies are a want.”
- “Compare my plan with an option called Lower income where monthly take-home income is SGD 3,500, and an option called More saving where savings are SGD 1,000.”
- “Use scenario More saving.”

The last instruction is matched to a stored scenario by the backend, not interpreted as a write by the model. It creates an **unsaved draft**, resets income-basis and expense-coverage confirmation, and requires review and final `confirm budget`. Generic confirmation cannot save a comparison. A model response cannot bypass the explicit scenario adoption step. Expired comparisons and comparisons whose saved budget changed require a fresh comparison. Names must be unique ASCII letters/numbers/spaces/hyphens/underscores (up to 40 characters); `Current plan` is reserved. Category deletion remains a Budget-page operation.

In the UI, users can compare the current editor values against one alternative, change the method, and see a table and stacked allocation chart. `Use option in editor` copies an option to a local unsaved editor draft. Saving requires confirmation of actual take-home income and expense coverage. Editing comparison inputs hides obsolete results until the user compares again. `Discard unsaved scenario` returns to saved values. The comparison panel supports SGD only.

### Stage-two contracts

- `BudgetMethod` is mirrored in the AI extraction and backend domain contracts. Supported method names, custom percentages and user-supplied category groups are validated at both boundaries.
- `BudgetDraft.action`: `plan` (default) or `compare`; `scenarios` contains up to three explicitly requested alternatives. Comparison metadata remains in conversation-scoped pending state with the existing 30-minute expiry.
- `services/budget_methods.py`: authoritative guidance calculation using Decimal arithmetic. Rounded targets sum to income, with the remaining cents assigned to savings.
- `services/budget_scenarios.py`: independent copies, override validation, comparisons and deterministic explanations. No persistence calls.
- `POST /api/users/{user_id}/budget/compare`: authenticated, owner-scoped, read-only calculation from an explicitly supplied draft. It returns no stored owner data and does not write budgets, profiles or conversations. Unlike Coach, which merges saved categories, the UI supplies the whole editor plan. Response includes `results`, `questions`, and `saved: false`.
- Saving still uses the existing budget API or Coach confirmation path. `BudgetPlanSettings.method` persists the selected method. Direct saves enforce classifications, valid percentages, affordability and the zero-based equality constraint.
- Stage two introduced `budget-planning-v2`; stage three expands the extraction contract to v3. Readers accept v1, v2 and v3 settings. The legacy general prompt-set version and baseline calculation are unchanged.

Offline fixture example, following the stage-one plan example: `scenario More saving: savings=1000`, then `use scenario More saving`. The fixture grammar supports one explicit scenario override at a time; the production extraction schema supports three. Live-model tests must separately verify multi-option language, gross versus take-home hypotheticals, method corrections and explicit adoption.

The confirmed plan now supplies `monthly_savings_capacity` to Budget and Goal Strategy. Its chosen savings allocation is the shared pool; unallocated income remains separate. The prior illustrative calculator is used only when no valid confirmed planning settings exist for the selected month, with an explicit fallback label. It retains the legacy 50/30/20 calculation **after recorded recurring expenses**; it is not the standard take-home-income interpretation of that rule. The new category-planning path does not use that baseline or publish its result as an observed savings balance.

## Stage three: spending reviews and adjustment proposals

Request **“Review my budget for September 2026”** in Coach, or open **Budget → Review recorded spending → Refresh spending review**. Coach asks for the month/year when missing; a read-only review does not require new income or savings inputs. Overview points to the Budget review panel. Reviews run on demand, without scheduled notifications or background jobs.

The backend reads only the authenticated profile's SGD expense aggregates. The cutoff is the earlier of Singapore today and the selected month's final day; future-dated entries are excluded. It includes unbudgeted categories and zero limits, and excludes recorded categories named `savings`, `emergency fund`, and `investments` from expense totals. Custom transfer aliases are not automatically recognized. Recurring rows are counted once. Transaction descriptions are not included in the review context. Foreign-currency budgets are reported as unsupported rather than converted.

Each category shows recorded expenses, saved limit, remaining amount, and status (over, approaching at 80%, within the recorded limit, or unbudgeted). A positive remaining amount does not establish an available cash balance or prove that commitments are paid. Records can be incomplete, including in a closed month. No saved budget is a valid review result; the user is asked to create a plan before adopting an adjustment.

### Pace calculation

Pace is an **illustration**, not a spending prediction or a variable-income forecast. It is available only for an in-progress month after at least seven calendar days have elapsed and when that category has non-recurring expense records on at least three distinct days:

```text
category month-end pace = recorded recurring expenses
                         + recorded non-recurring expenses / elapsed calendar days * days in month
remaining per day = max(category limit - recorded expenses, 0) / remaining calendar days
```

Recurring amounts are held constant to avoid multiplying a rent payment across the month. This does not infer unpaid bills. Non-recurring one-off purchases can still distort the illustration. Sparse, future and closed-month categories have no pace estimate. Remaining-per-day is omitted when there are no days left. Month lengths and leap years use calendar dates. An overall pace is shown only when every reviewed category has an estimate; missing values are never treated as zero. The UI shows recorded amounts and pace in separate chart series and labels unavailable estimates.

### Review → adjustment → confirmation

An overspent or unbudgeted category can produce a **Cover recorded spending** option: raise its limit to the recorded amount and preserve every other saved limit, method and savings allocation. This covers already-recorded expenses only; it does not guess an allowance for the rest of the month. A pace overrun alone prompts the user to inspect the spending pattern and does not generate an automatic numeric increase. The normal affordability and method checks identify funding gaps; the system never automatically cuts another category, essential commitment or savings target to fund an increase.

- Coach stores the option as a scenario comparison. `Use scenario Cover recorded spending` adopts an unsaved draft. Actual take-home income, expense coverage, missing inputs, and the final budget changes must still be confirmed. A review or generic `confirm budget` cannot directly authorize an adjustment.
- An existing pending plan/comparison is retained during a review and its old save confirmation is disarmed. Finish or cancel that draft before adopting the review's adjustment.
- The UI displays the proposed category limits and any funding gap. `Review adjustment in editor` opens an unsaved proposal. Legacy manual budgets without planning income/savings require those inputs through Coach or the method explorer first.
- A review evidence fingerprint covers the cutoff date, aggregate records and saved budget. Changed records, a new review date or changed saved limits require a fresh review before adoption. Evidence is retained through Coach clarification and checked again before saving. The UI sends `review_evidence` with a reviewed adjustment; a stale direct save returns HTTP 409. The user can still deliberately create or edit a separate manual budget through the existing API.

Stage-three modules are `services/budget_review.py`, repository `review_spending`, and `ui/budget_review.py`. `GET /api/users/{user_id}/budget/review?period_start=YYYY-MM-01` is authenticated, owner-scoped, and read-only. Its response includes the cutoff, coverage caveats, actual amounts, optional pace, suggestions, a non-persisting scenario comparison, `evidence_fingerprint`, and `saved: false`. `BudgetUpsert.review_evidence` is an optional transient precondition, not a database field. Model-provided numbers are not used to compute a review. Backend audit records `budget-review-v1`; extraction uses `budget-planning-v3` with `action=review`. Readers retain compatibility with v1/v2 planning settings. No additional database migration is required.

Tests cover ownership, currency, cutoff dates, transfers, zero limits, leap months, sparse data, recurring rows, independent comparison arithmetic, funding gaps, stale evidence, preservation of existing drafts, Coach adoption/clarification/confirmation and the UI review-to-editor flow. Live-model review phrasing and multilingual requests still need acceptance testing before release.

## Deployment

Apply migrations before starting the updated backend:

```powershell
cd C:\ai-financial-wellness-coach\apps\backend
C:\ai-financial-wellness-coach\.venv\Scripts\python.exe -m alembic upgrade head
```

Migration `20260929_0011` adds the nullable monthly budget planning column after `20260928_0010` (conversation drafts). Compose already runs migrations. Existing category limits need no backfill. Downgrading `0011` removes the planning metadata column; category limits remain.

The planning contract is independently versioned as `budget-planning-v3` in model extraction, deterministic output, saved settings, and backend response audit. Changes to this contract require a version update and refreshed planning tests. The general prompt-set version and its existing workflows remain unchanged.

## Verification and offline demonstration

Run these suites from their respective application directories:

```text
AI:       python -X utf8 -m pytest -p no:cacheprovider tests/test_budget_review.py tests/test_budget_methods.py tests/test_budget_planner.py tests/test_budget_capture.py
Backend:  python -X utf8 -m pytest -p no:cacheprovider tests/test_budget_review.py tests/test_budget_methods.py tests/test_budget_planning.py tests/test_budget_capture.py
Frontend: python -X utf8 -m pytest -p no:cacheprovider tests/test_budget_review.py tests/test_budget_methods.py tests/test_app.py tests/test_overview_budget.py
```

The tests cover explicit versus suggested amounts, one-month history selection, missing inputs, gross-income rejection, preserved commitments, funding gaps, no automatic cuts, owned/currency-scoped aggregates, prevention of recurring-expense double counting, HTTP confirmation and readback, and UI affordability checks.

The offline fixture is deliberately limited and is not evidence of production language understanding. Example:

1. `Plan my realistic budget for October 2026 in SGD; take home income: 4000; savings: 800; housing: 2700; hobbies: 700`
2. `all expenses included` — the backend reports the SGD 200 funding gap.
3. `hobbies: 500` — the revised proposal balances.
4. `confirm budget` — saves only after the complete preview.

Test live-model extraction separately with paraphrases, ambiguous currencies/dates, gross versus net income, corrections, incomplete spending records and unrelated follow-ups before release. Do not claim the offline fixture results as live-model acceptance.

## Remaining boundaries

The original three stages have now been extended by the four increments below. Background delivery (email/push), automatic rollover, bank connections and account-level reconciliation, variable-income forecasting, interest-aware debt payoff optimization, and category deletion through Coach remain outside this implementation. Cash-flow schedules support explicit weekly/annual frequencies; category budgets still require explicit monthly amounts. Non-SGD amounts and uncertain inputs require clarification. User-chosen goal contributions are modeled but never transferred automatically.


## Shared capacity source

The backend constructs owned `saved_budget_capacity` context using the requested `budget_period_start` (first day of a month), or Singapore's current month when omitted. Coach submits the workspace's selected month and displays that basis. Public clients cannot supply trusted capacity context. Manual budgets without confirmed planning settings, unsupported currencies and invalid saved plans cannot establish confirmed capacity.

Budget uses the saved monthly savings allocation and does not subtract recurring expenses again or redistribute unallocated income. Goal Strategy consumes that same capability, checks the combined monthly requirement of concurrently funded goals against one pool, and treats future feasibility as conditional on sustaining the amount. It does not reserve contributions or infer account balances. Capability fingerprints include the owned capacity context. Drafts, hypothetical scenarios and unconfirmed corrections never replace the saved source.

The read contract is backward compatible. No migration is required. Currency mismatches require clarification. The fallback still uses the legacy percentage calculation; its unconfirmed income basis and expense coverage are disclosed. Source-sensitive writer instructions apply to Budget and Goal Strategy; live-model acceptance remains separate from fixture and integration tests.


## Typed ledger and cash-flow workspace

Migration `20260930_0012` adds `transactions.transaction_type` (expense/income/transfer/refund, existing rows default to expense) and owned `planning_preferences`. Apply `alembic upgrade head` before using this version. Preferences are included in data export and cascade with owner deletion. The Transactions page supports choosing and editing a type. Existing Coach transaction capture remains expense-oriented; use Transactions to classify other flows.

Budget limits, reviews, date-spending queries and legacy spending analysis use **gross expense entries only**. Income, transfers and refunds are separate cash flows and never inflate expense totals. A refund is a positive cash inflow; this increment does not retroactively net it against an expense category. Existing savings-category transfer exclusions remain for legacy records until users classify them explicitly.

Budget → Cash flow, paydays and bills opens an explicit schedule editor. Users supply an SGD combined opening balance **at the start of a date**, plus income/bill amounts, categories, due dates and once/weekly/fortnightly/monthly/yearly frequency. Month-end dates clamp to the shorter month's last day while retaining the original day anchor. The API also supports schedule end dates. No frequency or bill payment is inferred from a recurring transaction flag.

The dated projection adds recorded income/refunds, subtracts recorded expenses, ignores internal transfers, and includes unsettled schedule occurrences through a user-selected horizon (maximum 365 days after opening). Future-dated ledger entries are excluded from actuals. Match recorded bill payments/refunds as described below, or mark unmatched paid/received occurrences settled; settlement does not create a transaction or move money. Overdue unsettled amounts remain explicit projected obligations. The result reports daily closing balances, the first shortfall date, and the lowest balance, with missing-record and within-day timing limitations. A balanced monthly total can still produce a shortage before payday.

Owned endpoints: `GET/PUT /api/users/{user_id}/cashflow/settings`, `GET /cashflow?through=YYYY-MM-DD`, and `POST /cashflow/settle?schedule_id=...&due_on=...`. Saving settings requires `confirmed: true`. No bank connection or automatic matching/payment is implemented. Explicit payment/refund matching is available as described below; individual bank-account reconciliation remains outside scope.


## Confirmed commitments and funded alternatives

In Budget, open **Fund goals and protect commitments** after saving a complete SGD plan. Choose protected categories, explicit savings minimum (including zero), maximum reduction percentage, category floors, selected owned SGD goals and their monthly contributions, and debt balances/minimum payments. Confirm and save these commitments separately from budget limits. They apply to this month; confirming revised commitments establishes a new reference for percentage reductions. No commitments are inferred from profile data or goal targets.

`GET/PUT /api/users/{user_id}/budget/commitments` reads/saves the owned period policy. `POST /budget/alternatives` accepts a first-of-month period and optional hypothetical take-home income/savings. Coach can request, for example, “Find funded alternatives for my budget for October 2026”; missing policies are directed to the confirmed workspace. The backend generates proportional and largest-adjustable-first reductions in integer cents. Protected limits, reduction caps, debt minimums and scheduled bills constrain the reductions. Distinct scheduled bills and separate debt minimums are added within a category. Only an explicit debt-to-bill link permits overlap: that obligation reserves the larger of its monthly scheduled total and debt minimum. The combined obligation total is then compared with category floors, protection and reduction limits. Existing debts with no explicit link/separate choice require review before further constrained saves or alternatives. All scheduled occurrences count toward monthly commitments, including already-settled bills.

Savings must cover the larger of the chosen savings target, confirmed minimum and combined goal contributions. Goal completion estimates use current recorded remaining amounts and constant chosen contributions, without growth or withdrawals. Debt balances are context; this increment does not calculate interest, payoff order or debt amortization. Alternatives expose any unresolved funding gap instead of overriding protections. A comparison writes no budgets. Adopt an option into the editor or use `use scenario NAME` in Coach, then confirm actual income, expense coverage and the exact budget. Existing method requirements still apply.

Repository saves and Coach previews recheck commitments, so deleting a protected category, omitting planning metadata or saving via another route cannot bypass them. Deleted or incompatible linked goals require updating the policy. Settings use the owned `planning_preferences` record introduced by migration `20260930_0012`, and follow owner export/deletion. Constraints are user-maintained and do not imply that recorded obligations are complete.


## Multi-month continuity and opt-in reviews

**Plan upcoming months** uses the selected saved source plan. Users enter a first target month, 1–12 months, the take-home income and savings to repeat in every target month, and a carry rule. Inputs are never filled from gross profile income. The available rules are:

- **Copy limits:** repeat the saved expense limits.
- **Carry surplus:** add each category's positive source-month remaining amount to the first target month's limit.
- **Carry net:** add surplus or deduct overspending in the first target month, with a minimum resulting limit of zero.

Carry rules require a completed source month and use gross recorded SGD expenses. Refunds are cash inflows, not negative expenses. Missing records or unbudgeted expenses can overstate apparent surplus; it is not verified cash. Carry is applied once; subsequent target months resume the source category limits, without invented future transactions. Existing target-month commitments are checked, while source-month policies are not copied. Configure each month's commitments separately. Each target's budgeting method, affordability and category validation remain authoritative; a surplus carry may need more funding and is never silently taken out of savings.

`POST /api/users/{user_id}/budget/continuity/preview` stores a single owned, expiring preview (30 minutes); it does not write budgets. It returns exact category limits, repeated income/savings, prior target plans, funding gaps and questions. Existing target plans require explicit `allow_overwrite`. `POST /budget/continuity/confirm` requires that preview ID and `confirmed: true`. All plans save in one transaction, and the preview is consumed once. Changes to source or target plans, relevant spending, target commitments/linked goals, schedules, or the Singapore date invalidate it. Validation or write failure leaves the batch unapplied. The UI separately confirms actual income, expense coverage, exact limits and replacements. Coach supports the same multi-month previews and atomic confirmation through a conversation-scoped draft. It requires explicit confirmation that actual take-home income, savings and expense coverage apply to every target month.

**Periodic budget reviews** is disabled by default. Users explicitly choose weekly or monthly cadence and a first date, then confirm preferences. Weekly due reviews inspect the current calendar month; monthly due reviews inspect the last completed month. Reminders appear on Overview and in Budget when the app is opened; this is not a background scheduler or external notification service. The due reminder persists until marked reviewed or disabled. Marking reviewed verifies current evidence and advances the next date from the acknowledgment date (seven days or one calendar month). It never adopts suggestions or changes budgets. Missing budgets/data remain visible as review warnings.

Owned endpoints:

- `GET/PUT /api/users/{user_id}/budget/reviews/preferences`
- `GET /api/users/{user_id}/budget/reviews/due`
- `POST /api/users/{user_id}/budget/reviews/acknowledge` with the displayed evidence fingerprint and explicit confirmation

All continuity and review state uses `planning_preferences`; owner export and deletion include it. No additional migration beyond `20260930_0012` is required for these features. Existing deployments must apply migrations through that revision before running this code. The subsequent 2026-09-29 release applied and verified these migrations before updating the backend.

## Roadmap verification

The extended extraction/planning contract is `budget-planning-v4`; saved planning settings from v1–v3 remain readable.

Regression coverage includes confirmed-plan cross-agent sourcing, explicit typed cash flows, pre-payday shortages, settled occurrences, protected category and goal/debt minimums, infeasible alternatives, read-only Coach comparisons, preview expiration and ownership, stale evidence, duplicate confirmation, all-or-nothing monthly writes, opt-in review dates, and UI confirmation gates. Local fixtures exercise the model contract; the focused deployed acceptance result is recorded below. The Windows environment cannot run the existing symlink-dependent AI test without symlink privilege; the rest of the AI suite is run with that test excluded.


## Deployed Budget acceptance

After a successful release, dispatch **Budget Live Acceptance** (`budget-live-acceptance.yml`) on the deployed main revision. It runs nine focused cases twice by default against the deployed Coach, checking real OpenAI model/prompt provenance, custom-category extraction, ambiguous dates/currency, gross-income clarification, an unaffordable plan, confirmed-commitment alternatives, multi-month clarification, Chinese category extraction, a cash-flow preview, and refund clarification. It sends no save confirmation and removes its synthetic chat sessions. The checks require every case to pass; a 30-second P95 ceiling bounds this multi-agent planning path. The inherited token-cost estimate is diagnostic and is not billing evidence. Privacy-safe check results and correlation IDs are retained as an Actions artifact for 90 days. This focused suite supplements the release smoke and existing general live evaluation; it is not comprehensive acceptance of every UI flow.


### Deployed verification, 2026-09-29

Application revision `f821887a62e8b8d94aa77975f34d6770042e6312` passed [CI](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36566192931) and [AWS release](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36566489405), including all three services, database migration verification and post-deployment health/AI safety smoke. [Budget Live Acceptance](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/36568248515) passed all seven cases twice (14/14), using GPT-6 Luna and prompt set v6, with P50 11.67 seconds and P95 17.42 seconds. All synthetic chat sessions were cleaned up. Artifact `budget-live-acceptance-36568248515` expires on 2026-12-28.

Earlier live runs exposed Chinese capture routing, hidden funding-gap feedback during clarification, and safety-review ambiguity around read-only workflow handoffs. These were corrected and verified with the same cases and unchanged acceptance thresholds. The passing result validates this bounded suite; it does not establish comprehensive production or all-UI acceptance.


## Unified obligations and explicit reconciliation (workspace v1)

Bills have stable schedule IDs. Each debt commitment now requires either a corresponding owned expense bill in the same category or an explicit **Separate obligation** choice. A bill can represent only one debt commitment per month. The Budget editor presents named choices; identical categories never imply overlap. Removing or changing the category/type of a bill referenced by debt commitments requires revising those commitments first. Existing budgets are retained; legacy debt policies require a user decision rather than an automatic migration of their meaning.

Open **Cash flow, paydays and bills → Open bill matching**. Choose a recorded SGD expense or refund, a bill, its occurrence due date, amount, and effect. Preview and explicitly confirm. Matching supports partial payments and splitting a transaction across occurrences; cumulative allocations cannot exceed the transaction amount or overpay an occurrence. An excess payment remains unmatched. Refunds require one of two explicit choices:

- **Amount becomes payable again:** cash is refunded, net paid decreases, and the unpaid bill remainder increases.
- **Bill amount is reduced:** cash is refunded and both the obligation and net paid decrease; the unpaid remainder is unchanged.

Refund allocations cannot exceed payments or precede the payment balance they reverse. A future-dated record cannot settle an occurrence early. Projections count the actual cash flow once and project only the unmatched bill remainder. Monthly budget spending and carry-forward still use gross expenses; reconciliation does not rewrite transactions, net category spending, update debt balances, or transfer money. Opening balances must already reflect transactions before their opening date; occurrences outside the projection's opening/horizon are not included. Scheduled income retains manual settlement; matching currently covers expense bills only.

A matched transaction cannot be edited/deleted until its matches are removed. A matched bill's financial terms cannot change until its matches are removed (renaming is allowed). Refund-dependent payment matches cannot be removed until the dependent refund matches are removed. **Remove manual settlement** makes a legacy manually settled occurrence available for matching. A matched occurrence cannot also be manually settled. These checks apply to both UI and Coach paths.

The selector/Coach context includes the latest 100 owned SGD expense/refund records, with available amounts, and saved links. Users choose records explicitly; no bank feed or automatic fuzzy match is involved. At most 5,000 allocations are supported in one workspace. Links use the existing owned `planning_preferences.reconciliation` JSON section and inherit export/erasure. No new migration is required beyond `20260930_0012`.

## Conversational planning commands (workspace v1)

Coach can now propose and confirm cash-flow settings, protected categories, floors, goal contributions, linked/separate debts, payment/refund matches, match removal, multi-month plans, and in-app review preferences. Examples:

- “Protect housing in my October 2026 commitments; contribute SGD 300 monthly to my Emergency reserve goal.”
- “Add a monthly Rent bill of SGD 1500 in housing starting October 5, 2026.” Coach asks for any missing opening date/balance/currency or ambiguous existing bill.
- “Match SGD 600 of my recorded September 5 rent payment to the Rent bill due September 5, 2026.” Ambiguous records, dates, amounts or refund effects require clarification.
- “Copy September 2026 limits into October through December 2026; take-home income SGD 4000 and savings SGD 800 each month.” Coach asks for coverage confirmation and previews every target before saving.

The model emits only an untrusted `workspace` command draft (`operation` plus JSON-encoded fields). Backend Pydantic schemas reject unknown fields and validate dates, amounts, ownership and references. Existing top-level settings are retained when omitted; explicitly supplied collections replace in full and appear in the preview. Pending fields survive clarification/corrections. The model cannot set the trusted confirmation flag or bypass missing inputs. Saved records are context, never instructions.

The backend displays exact normalized values and requires a subsequent `confirm budget` (or supported confirmation reply). Corrections and unrelated/blocked replies disarm prior previews; cancellation discards the draft. Previews expire after 30 minutes. Changes to owned planning settings, relevant records, budgets, goal balances or the Singapore date invalidate confirmation. User-scoped locking serializes workspace mutations and linked transaction guards. Coach previews belong to their chat and do not overwrite the Budget page's batch or workspace preview. Confirmed changes are committed with the chat response; batch budgets are atomic. Repeated confirmation cannot replay a consumed preview.

Owned API endpoints:

- `GET /api/users/{user_id}/budget/workspace` — owned settings, goal references and reconciliation records.
- `POST /budget/workspace/preview` — `{operation, payload_json}`; validates and stores a UI preview without applying it.
- `POST /budget/workspace/confirm` — `{preview_id, confirmed: true}`; verifies evidence and consumes the preview.
- Existing settlement endpoint accepts `settled=false` to explicitly remove manual settlement.

The command contract/audit is `budget-workspace-v1`; the monthly allocation contract remains `budget-planning-v4`. Offline model fixtures are intentionally limited. Stubbed orchestration and HTTP integration tests verify contract forwarding and confirmation behavior, not natural-language extraction quality. The expanded nine-case live dataset is prepared for the next deployed acceptance run; the older 14/14 result above applies only to revision `f821887`, not these new capabilities.


## Cash-flow-aware alternatives

Budget's **Can this plan last until payday?** panel and Coach `timing` command accept explicit spending timing (evenly each day, start, or month end), planning start date, savings reserve date, minimum spendable balance and record-coverage confirmation. The projection subtracts recorded expenses and unpaid scheduled bills from each category first; only the remaining category limits follow the chosen pattern. Savings are earmarked in full on the chosen date. This models spendable cash, not a bank-account withdrawal or verified balance.

Funded alternatives include the resulting lowest spendable amount, first date below the chosen minimum, gap, unpaid/upcoming bills, questions and a daily chart. Overview shows the same assessment for the saved plan. Monthly affordability and cash timing are separate results: an affordable monthly budget may still run short before payday. No dates are automatically moved and no lending is assumed. An alternative income amount must match explicit recorded/payday income before timing can be described as within the buffer. Overdue unreceived income or spending/bills above a category limit requires clarification.

Settings are confirmed through the existing expiring workspace preview, stored per month. Outdated spending start dates require a fresh choice. Opening balances must be on/before the month and within the 365-day projection horizon. Income settlements and record completeness remain essential; end-of-day projections do not establish within-day liquidity. Targeted tests cover monthly balance with a pre-payday shortage, chosen timing, reductions, changed hypothetical income, record overrun and stale timing.
