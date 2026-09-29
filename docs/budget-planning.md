# Budget planning: first-stage implementation

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

- `apps/ai-service/app/agents/budget_capture.py`: typed extraction contract for user inputs and corrections, versioned as `budget-planning-v1`. The model interprets language; it cannot write budgets.
- `apps/ai-service/app/tools/budget_planner.py`: allowlisted deterministic category proposals, provenance, expense totals and funding gaps. It does not use 50/30/20 to generate a category plan.
- `apps/ai-service/app/orchestrator.py`: `budget_planning` intent, continuity for pending planning drafts, and role-scoped aggregate context. Only planning Budget tasks receive `planning_context`; no raw transaction descriptions are added to this context.
- `apps/backend/app/services/budget_planning.py`: owned SGD aggregate construction, required planning inputs, authoritative affordability arithmetic and explanation.
- `apps/backend/app/services/budget_capture.py`: preview, independent recomputation over the merged plan, explicit confirmation, conflict checking and atomic persistence. Dropping the planning object cannot bypass checks on an existing planning draft.
- `BudgetUpsert.planning` / `BudgetResponse.planning`: nullable `BudgetPlanSettings` containing `take_home_income`, `savings_target`, confirmed `income_basis`, `expenses_confirmed`, and planner `version`. The API validates expenses plus savings against income whenever planning settings are supplied.
- `MonthlyBudgetRecord.planning`: nullable JSON column. Existing budgets remain valid with null planning settings. Planning metadata is included in owner data export and follows the monthly budget's ownership/deletion lifecycle.

Pending drafts use the existing conversation-scoped JSON field. Preview expiry (30 minutes), changed-budget detection, re-confirmation after intervening turns, and atomic budget/draft/chat commits remain in force. Saved plan settings participate in conflict detection. Public Coach requests cannot supply trusted pending drafts or aggregate context.

The Budget and Overview pages show take-home income, the separate savings allocation, and unallocated income for saved plans. The Budget form preserves these settings, requires confirmation of expense coverage when editing, and prevents saving a funding gap. Direct API clients editing a planned budget should round-trip its `planning` settings; this optional field distinguishes a planned budget from a legacy manual category budget.

The prior illustrative calculator remains available for baseline guidance and `monthly_savings_capacity` dependencies. It retains the legacy 50/30/20 calculation **after recorded recurring expenses**; it is not the standard take-home-income interpretation of that rule. The new category-planning path does not use that baseline or publish its result as an observed savings balance.

## Deployment

Apply migrations before starting the updated backend:

```powershell
cd C:\ai-financial-wellness-coach\apps\backend
C:\ai-financial-wellness-coach\.venv\Scripts\python.exe -m alembic upgrade head
```

Migration `20260929_0011` adds the nullable monthly budget planning column after `20260928_0010` (conversation drafts). Compose already runs migrations. Existing category limits need no backfill. Downgrading `0011` removes the planning metadata column; category limits remain.

The planning contract is independently versioned as `budget-planning-v1` in model extraction, deterministic output, saved settings, and backend response audit. Changes to this contract require a version update and refreshed planning tests. The general prompt-set version and its existing workflows remain unchanged.

## Verification and offline demonstration

Run these suites from their respective application directories:

```text
AI:       python -X utf8 -m pytest -p no:cacheprovider tests/test_budget_planner.py tests/test_budget_capture.py
Backend:  python -X utf8 -m pytest -p no:cacheprovider tests/test_budget_planning.py tests/test_budget_capture.py
Frontend: python -X utf8 -m pytest -p no:cacheprovider tests/test_app.py tests/test_overview_budget.py
```

The tests cover explicit versus suggested amounts, one-month history selection, missing inputs, gross-income rejection, preserved commitments, funding gaps, no automatic cuts, owned/currency-scoped aggregates, prevention of recurring-expense double counting, HTTP confirmation and readback, and UI affordability checks.

The offline fixture is deliberately limited and is not evidence of production language understanding. Example:

1. `Plan my realistic budget for October 2026 in SGD; take home income: 4000; savings: 800; housing: 2700; hobbies: 700`
2. `all expenses included` — the backend reports the SGD 200 funding gap.
3. `hobbies: 500` — the revised proposal balances.
4. `confirm budget` — saves only after the complete preview.

Test live-model extraction separately with paraphrases, ambiguous currencies/dates, gross versus net income, corrections, incomplete spending records and unrelated follow-ups before release. Do not claim the offline fixture results as live-model acceptance.

## Deliberately deferred

This stage does not implement method selection, custom percentage strategies, scenario comparison, automatic spending reviews, multi-month plans, rollover, annual/weekly conversions, variable-income forecasting, goal prioritization, or category deletion through Coach. Savings are a user-selected monthly total; no automatic goal contribution or debt payoff schedule is inferred. Non-SGD amounts and uncertain monthly amounts require clarification.
