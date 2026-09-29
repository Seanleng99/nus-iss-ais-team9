# Budget planning: plans, methods, scenarios and spending reviews

Status: implemented locally; deterministic/unit and API/UI integration tests are the verification baseline. Live-model acceptance and deployment are separate activities.

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

## Deliberately deferred

The first three stages do not implement scheduled/background reviews or notifications, multi-month plans, rollover, annual/weekly conversions, variable-income forecasting, goal prioritization, or category deletion through Coach. Savings are a user-selected monthly total; no automatic goal contribution or debt payoff schedule is inferred. Non-SGD amounts and uncertain monthly amounts require clarification.


## Shared capacity source

The backend constructs owned `saved_budget_capacity` context using the requested `budget_period_start` (first day of a month), or Singapore's current month when omitted. Coach submits the workspace's selected month and displays that basis. Public clients cannot supply trusted capacity context. Manual budgets without confirmed planning settings, unsupported currencies and invalid saved plans cannot establish confirmed capacity.

Budget uses the saved monthly savings allocation and does not subtract recurring expenses again or redistribute unallocated income. Goal Strategy consumes that same capability, checks the combined monthly requirement of concurrently funded goals against one pool, and treats future feasibility as conditional on sustaining the amount. It does not reserve contributions or infer account balances. Capability fingerprints include the owned capacity context. Drafts, hypothetical scenarios and unconfirmed corrections never replace the saved source.

The read contract is backward compatible. No migration is required. Currency mismatches require clarification. The fallback still uses the legacy percentage calculation; its unconfirmed income basis and expense coverage are disclosed. Source-sensitive writer instructions apply to Budget and Goal Strategy; live-model acceptance remains separate from fixture and integration tests.
