# Agent reasoning demo: prompts for review

Prepared 7 October 2026 and reused in the retained v10 browser runs. This is the reusable synthetic setup and expectation catalogue, rather than a current acceptance report. The [latest retained retest](agent-reasoning-live-test-results-2026-10-09-post7356713.md) records 34 original turns, additional case 35 and seven planned repeats at build `7356713`. The [preceding v10 baseline](agent-reasoning-live-test-results-2026-10-09.md) remains available for the recovery diagnosis. Profile setup was completed through the application. All prompts below request analysis, calculations, explanations, comparisons or read-only forecasts. They do not request changes to budget, transaction or goal records.

The original prompts target the **current v10 catalogue** with conditional financial dependencies. Retired v9 reports and their earlier failures remain recoverable from Git. Saved-goal arithmetic can run independently; funding feasibility requires Budget capacity. An expected route is a test assertion, not a guarantee. Evaluate the current implementation with the executable v2 orchestration suite and identify the tested build, prompt hash and provider in every new report.

## Profile and records created

- Name: **Agent Reasoning Demo — Synthetic**
- Profile ID: `agent-reasoning-demo-20261007`
- Monthly income: **SGD 6,500**; employed, stable income, renting; household size three, one dependant.
- Risk preference: Moderate; financial literacy: Intermediate.
- Language: English; accessibility preferences: Plain Language and Step-By-Step Explanations.
- Default sidebar period left at **October 2026**.
- Three saved monthly budgets, each with eight category limits and a separate savings allocation.
- **25 recorded expenses**: thirteen in September, twelve in October. No November expenses.
- **Four saved goals**, with targets, existing balances and durations.
- October rent has an explicit monthly recurrence: first payment 1 October 2026, next due 1 November 2026, interval one month, no end date. Other entries are not marked recurring.

### Budget plans and recorded expense totals

All amounts are SGD. Category figures are planned expense limits, not monthly actuals.

| Category | September plan | October plan | November plan | September recorded | October recorded |
|---|---:|---:|---:|---:|---:|
| Housing | 1,800 | 1,800 | 1,800 | 1,800 | 1,800 |
| Food | 750 | 650 | 700 | 680 | 660 |
| Transport | 250 | 300 | 350 | 200 | 175 |
| Utilities | 200 | 250 | 250 | 160 | 180 |
| Healthcare | 200 | 200 | 200 | 120 | 95 |
| Education | 200 | 250 | 400 | 160 | 120 |
| Entertainment | 250 | 200 | 200 | 240 | 225 |
| Shopping | 250 | 300 | 300 | 210 | 320 |
| **Expense total** | **3,900** | **3,950** | **4,200** | **3,570** | **3,575** |
| **Saved savings allocation** | **1,400** | **1,600** | **1,000** | — | — |
| **Unallocated planned income** | **1,200** | **950** | **1,300** | — | — |

October Food is SGD 10 over its limit, Entertainment SGD 25 over, and Shopping SGD 20 over. The overall expense limit still exceeds recorded expenses by SGD 375. This is useful for testing the difference between an overall total and individual category overruns.

October entries cover 1–6 October; September entries cover 1–26 September. These synthetic records do not establish complete observed monthly expenditure. Comparisons must preserve that limitation. The saved budgets were entered with confirmed income and expense-plan coverage; that confirmation concerns the plan, not the completeness of the transaction ledger.

The Overview displays SGD 2,925 as income minus October recorded expenses. That figure is **not** the confirmed SGD 1,600 monthly savings allocation and is not evidence of an actual savings account balance. This distinction is intentional test data.

### Saved goals

| Goal | Target | Already saved | Remaining | Months | Required per month |
|---|---:|---:|---:|---:|---:|
| Demo Laptop Upgrade | 3,600 | 600 | 3,000 | 6 | 500 |
| Demo Travel Fund | 6,000 | 1,200 | 4,800 | 12 | 400 |
| Demo Professional Course | 4,800 | 800 | 4,000 | 8 | 500 |
| Demo Home Deposit | 24,000 | 2,400 | 21,600 | 18 | 1,200 |
| **Combined** | | | | | **2,600** |

Equal contributions, no assumed investment returns. Funding all four concurrently creates a monthly shortfall of SGD 1,200 against September's allocation, SGD 1,000 against October's, and SGD 1,600 against November's. Each goal individually fits October's pool; they cannot all independently consume that same pool.

## How to interpret expected routing

Notation: **S** = Spending; **B** = Budget; **G** = Goal Strategy; **I** = Investment Education. `B → S` means Budget requests Spending's output; the data flows back from Spending to Budget. `G → B → S` means Goal waits for Budget capacity and Budget requests Spending context. `+` means multiple specialists; it does not by itself prove concurrency.

Every ordinary completed run also has Risk and Compliance review. “Single specialist” here counts the four domain specialists, excluding that mandatory reviewer. Tool calls and helper grounding executions should be distinguished from an independently routed specialist narrative.

For isolated routing tests, later run each standalone case in a fresh Coach conversation with automatic selection and October selected. Cases explicitly naming another period override the sidebar. Follow-up cases deliberately use one conversation. Independent Goal tests now use saved records and ask for arithmetic rather than affordability.

The supported specialist dependency edges are:

| Requester | Capability | Provider | Status |
|---|---|---|---|
| Budget | `transaction_category_totals` | Spending | Optional context dependency when Budget's own work uses recorded expenses |
| Goal | `monthly_savings_capacity` | Budget | Required for funding feasibility; absent for saved-goal arithmetic |
| Budget or Goal | `education_context` | Education retrieval grounding | Conditional tool dependency for investment concepts |

**There is no direct Spending–Goal dependency edge; it remains deferred.** Saved-goal funding feasibility pulls in Budget even if the initial router selected only Goal. Remaining amounts, progress and equal monthly contribution arithmetic can use the four saved goals without Budget.

## Your twelve requested scenarios

### 1. Spending: single specialist

> Analyze my Food, Entertainment and Shopping patterns in September 2026 and October 2026. Identify the largest changes and explain what the date coverage allows you to conclude.

Expected: **S**. Check category totals and date coverage; October being partial must qualify the comparison. No budget limit assessment or goal feasibility is requested.

### 2. Budget: single specialist

> What monthly savings capacity does my October 2026 budget's confirmed plan provide? Explain the calculation and distinguish the savings allocation from unallocated income.

Expected: **B**, without `B → S`. Check SGD 1,600 savings allocation, SGD 950 unallocated planned income, SGD 3,950 planned expenses, and SGD 6,500 income. The unused plan residual must not automatically become the goal funding pool.

### 3. Goal: single specialist

> Calculate the remaining amount, percentage progress and equal monthly contribution for each of my saved goals using its recorded balance and duration.

Expected: **G**, with no income or Budget dependency. Monthly contributions: Laptop SGD 500, Travel SGD 400, Course SGD 500, Home Deposit SGD 1,200. This asks for saved-record arithmetic, not funding feasibility.

### 4. Investment: single specialist

> Explain how shares, bonds, mutual funds and ETFs differ, especially diversification and liquidity. Give a neutral comparison with sources where available.

Expected: **I**. Check support for each requested concept, accurate citations where present, and visible qualification of any permitted model-knowledge section. This asks for education, not personal investment selection.

### 5. Budget + Spending: dependency

> Explain my October 2026 monthly savings capacity using my budget and spending patterns. Which observed categories put pressure on the plan? Distinguish planned capacity from money already saved.

Expected: **B + S**, with **`B → S`** for `transaction_category_totals`. Capacity remains grounded in the confirmed plan; recorded totals provide context. Do not automatically subtract every recorded expense again from a plan that already allocates expenses.

### 6. Budget + Goal: dependency

> Using my October 2026 budget's confirmed savings allocation, can I fund all my saved goals concurrently at their recorded monthly rates? Explain individual feasibility and feasibility against one shared pool.

Expected: **B + G**, with **`G → B`** for `monthly_savings_capacity`. Check SGD 2,600 combined requirement, SGD 1,600 capacity, SGD 1,000 shortfall. If Budget was already selected and produced the matching capability, Goal should reuse it.

### 7. Budget + Spending + Goal: dependency

> Use my October 2026 spending patterns and saved budget capacity to assess all my saved goals together. Explain recorded expense pressures, required monthly contributions and the total shortfall.

Expected: **S + B + G**, with **`G → B → S`**. Check both capability edges, provider reuse where applicable, and Goal resumption. The spending narrative and Budget capacity should preserve their different meanings.

### 8. Spending + Goal: dependency requested, exact pair unsupported

> How do my October 2026 spending patterns affect whether I can fund my saved goals together?

Expected initial intent: **S + G**. Expected final specialist set: **S + B + G**, with **`G → B → S`**. This is a useful test that the orchestrator adds Budget. It cannot demonstrate a direct two-agent Spending–Goal dependency in the current registry.

### 9. Budget + Spending: independent parallel candidates

> Analyze my spending by category. Independently explain zero-based budgeting as a general method.

Expected: **S + B**, with no specialist dependency edge. The first task uses records; the second is a conceptual explanation. Under v9, a spending keyword in the independent part is intended to leave Budget independent. The live run nevertheless requested `B → S` and failed this assertion; see the results report.

### 10. Budget + Goal: independent parallel candidates

> Explain zero-based budgeting as a general method. Independently calculate the remaining amount and equal monthly contribution for each of my saved goals.

Expected: **B + G**, with no specialist dependency edge. Goal uses saved balances and durations; Budget answers the conceptual question. No affordability conclusion or income requirement should be introduced.

### 11. Budget + Spending + Goal: independent parallel candidates

> Analyze my spending by category. Separately explain zero-based budgeting as a general method. Independently calculate the remaining amount and equal monthly contribution for each of my saved goals.

Expected: **S + B + G**, with no specialist dependency edge. Preserve three distinct answers from recorded expenses, general Budget concepts and saved-goal arithmetic. Budget's conceptual explanation has no need to consume Spending totals.

### 12. Spending + Goal: independent parallel candidates

> Analyze my spending by category. Independently calculate the remaining amount and equal monthly contribution for each of my saved goals.

Expected: **S + G**, with no specialist dependency edge and no Budget added. Changing the Goal part to funding feasibility would introduce Budget.

## Missing specialist combinations

Four specialists have fifteen nonempty combinations. Your list covers eight distinct specialist sets; seven additional sets include Investment alongside other specialists. The following cover those remaining sets. Independent Goal parts use saved-record arithmetic; trace verification is still required.

| ID | Additional scenario | Prompt for review | Expected structure |
|---|---|---|---|
| 13 | Spending + Investment | Analyze my recorded purchases by category. Independently explain diversification and the difference between shares and bonds. | **S + I**, independent candidates |
| 14 | Budget + Investment | Explain my October 2026 budget's confirmed monthly savings capacity. Independently explain diversification as a general investment concept. | **B + I**, independent candidates |
| 15 | Goal + Investment | Calculate the remaining amount and equal monthly contribution for each saved goal. Independently explain diversification as a general investment concept. | **G + I**, saved-goal arithmetic; no Budget expected |
| 16 | Budget + Spending + Investment | Use my October 2026 spending patterns to explain my budget's monthly savings capacity. Independently explain diversification as a general investment concept. | **B → S**, while **I** can run independently |
| 17 | Spending + Goal + Investment | Analyze my spending by category. Independently calculate the remaining amount and equal monthly contribution for each saved goal. Separately explain diversification as a general investment concept. | **S + G + I**, independent candidates; saved-goal arithmetic |
| 18 | Budget + Goal + Investment | Assess all my saved goals together against my October 2026 budget's confirmed savings allocation. Independently explain diversification as a general investment concept. | **G → B**, while **I** can run independently |
| 19 | All four specialists | Use my October 2026 spending patterns and budget's confirmed savings allocation to assess all my saved goals concurrently. Independently explain diversification as a general investment concept. | **G → B → S**, while **I** can run independently |

Useful independent variants of 16, 18 and 19:

- **16P:** “Analyze my recorded purchases by category. Independently explain zero-based budgeting as a general method. Separately explain diversification as a general investment concept.” Expected **S + B + I**, no specialist edge.
- **18P:** “Explain zero-based budgeting as a general method. Independently calculate the remaining amount and equal monthly contribution for each saved goal. Separately explain diversification as a general investment concept.” Expected **B + G + I**, no specialist edge.
- **19P:** “Analyze my spending by category. Independently explain zero-based budgeting as a general method. Separately calculate the remaining amount and equal monthly contribution for each saved goal. Independently explain diversification as a general investment concept.” Expected **S + B + G + I**, no specialist edge.

## Other useful scenarios missed by a combination list

### 20. Goal dynamically adds Budget

> Are all my saved goals feasible together against my current monthly savings capacity? Explain the combined shortfall.

Expected: Goal requires `monthly_savings_capacity`, adding Budget if it was not initially selected. The initial semantic router may already select both; the trace must distinguish scheduling a new provider from reusing one. This demonstrates dependency discovery better than a prompt that explicitly names every domain.

### 21. Recurrence reasoning: projected versus recorded expenses

> Which explicitly scheduled recurring expenses are due in November 2026, and what is their projected total? Explain the difference between a forecast and recorded payments.

Expected: **S** with the read-only forecast path. One scheduled rent payment, SGD 1,800 on 1 November. Similar-looking September rent and October streaming descriptions do not establish additional recurrence rules. No November payment should be described as already paid.

### 22. Saved plan with no observed expenses

> Analyze my November 2026 expense patterns and explain whether the records support a comparison with October 2026.

Expected: **S**. No November expenses are recorded. Historical October records and a November recurring forecast are not observed November transactions. Zero records is not proof of zero expenses.

### 23. Calendar scope and competing goals

> Using the confirmed budget savings allocations for September 2026, October 2026 and November 2026, assess whether all my saved goals can be funded concurrently in each month. Compare the shortfalls.

Expected: **B + G**, `G → B`, with period-specific capacity. Check shortfalls of SGD 1,200, SGD 1,000 and SGD 1,600 respectively. Do not distribute a summed three-month pool back into months or reuse October for every month.

### 24. Missing requested budget

> Assess whether all my saved goals can be funded together using my December 2026 saved budget's savings allocation.

Expected: **B + G**, `G → B`, with December capacity unavailable. Goal arithmetic can still be explained, but no December affordability conclusion should borrow October's saved plan or silently use a generic baseline.

### 25. Emergency-fund special path

> Explain how an emergency fund is sized and what my recorded expenses can tell me about a suitable reserve benchmark. Explain any missing information.

Expected: **G**, or **S + G** when the model separates the explicitly requested recorded-expense analysis, with conditional `education_context` grounding. The ordinary saved-goal Budget dependency is bypassed. The four saved goals do not include an emergency fund. Do not declare a personal reserve adequate from incomplete logs. This expectation clarifies acceptable semantic variation; it does not change the historical timeout verdict.

### 26. Follow-up subject resolution

First turn:

> Explain mutual funds and ETFs as two numbered options, in that order, and compare how they work.

Then, in the same conversation:

> Explain the second option with a simple analogy.

Expected: **I** again, resolving the displayed second option to ETFs. Resolve against the answer's actual displayed order and grounded referents; do not assume that hidden specialist ordering establishes the displayed option order.

### 27. Ambiguous follow-up in a fresh conversation

> Explain the second option with a simple analogy.

Expected: clarification because no usable preceding option list exists. The system should not invent an ETF referent from another conversation.

### 28. Response preferences without changing reasoning

> Assess all my saved goals together against my October 2026 budget's confirmed savings allocation. Use plain English, a compact comparison table and a short explanation of the shared-pool shortfall.

Expected: **B + G**, `G → B`. Same SGD 2,600 requirement, SGD 1,600 pool and SGD 1,000 shortfall as case 6. Style and accessibility preferences should change presentation, not authoritative numbers, period or dependency behavior.

### 29. Partial education answerability

> Explain diversification and compare it with the current tax treatment of ETFs for my situation. Clearly identify which parts you can support.

Expected: **I**. General supported education can be answered; current tax and personal eligibility claims are outside the permitted general-knowledge fallback. Preserve an explicit scope limitation rather than pretending the broad diversification evidence supports tax advice. This is an evidence/scope test, not a source of actual tax guidance.

### 30. Conditional Education grounding versus a separately routed Investment answer

Candidate:

> Explain my October 2026 budget's confirmed savings capacity and why liquidity matters when considering that savings pool.

The router may select **B + I** because an investment concept is explicit. In that case Budget suppresses duplicate optional Education retrieval and Investment owns the concept explanation. If the router selects only Budget, Budget can request `education_context` for the concept. Natural-language wording cannot guarantee which path the semantic router chooses. To prove this particular capability edge, a controlled test should select Budget only; that has not been run here.

## Trace checks and recorded execution

The [latest retained live results](agent-reasoning-live-test-results-2026-10-09-post7356713.md) distinguish the assertions below from observed behavior and verify unchanged financial records. That run observed localized corrections and Budget-only Education in case 30R, whose delivered answer was incomplete. It did not provide controlled fault injection or prove reliable recovery across arbitrary requests. A forced Budget-only harness check and a naturally chosen browser route measure different scopes.

For each case, record the initially routed agents and the final agent set separately. Check task outcomes and `dependency.requested`, `dependency.scheduled`, `dependency.resolved` and `task.resumed` events, including the capability and requester/provider identity. A `reused` resolution is a real dependency satisfied from matching existing output; it does not mean the tasks were independent.

For parallel cases, check **absence of the relevant specialist dependency edges** and overlapping ready-task execution timestamps. An agent list, answer ordering or a statement saying “independently” is insufficient evidence of concurrent execution. Concurrency also depends on the deployment's configured worker capacity.

Check recorded versus projected expenses, exact requested month, saved plan versus illustrative baseline, shared versus per-goal capacity, complete coverage of the user question, and citations/model-knowledge labels for Investment. Retain Compliance outcomes in the evidence.

Retryable errors and semantic repair are runtime conditions, not reliably triggerable user intents. Testing them requires controlled failures or a deliberately incomplete allowed Education draft in a test harness. Do not claim a normal prompt proves retry or repair merely because the final answer succeeded.

## Local implementation references

- Routing, task scheduling, dependency resolution, synthesis and review: `apps/ai-service/app/orchestrator.py`
- Allowed edges: `apps/ai-service/app/capabilities/registry.py`
- Budget spending dependency: `apps/ai-service/app/agents/budget.py`
- Conditional saved-goal capacity, arithmetic and illustrative exception: `apps/ai-service/app/agents/goal_strategy.py`
- Router and requirement instructions: `apps/ai-service/prompts/current/prompts.json` (manifest release v10)
- Policy changes and rollout status: [Conditional financial dependencies](conditional-financial-dependencies.md)
- Calendar recurrence: `apps/shared/coach_math/recurrence.py`
- Dependency scheduling/reuse examples: `apps/ai-service/tests/test_dynamic_dependencies.py`

For the detailed explanation of the additional concepts and what is essential to the demonstration, see [Current orchestration implementation](orchestration-current-implementation-2026-10-07.md).

## Additional full-chain demonstration after the 8 October diagnosis

The historical case 7 wording permits Spending to report expense pressures separately while Goal consumes saved Budget capacity. For an explicit full-chain demonstration, use the additional evaluation case 35 below; this does not change the original live verdict.

> First analyze my recorded October 2026 spending by category. Have Budget reconcile those category totals against my saved October limits and explain expense pressures alongside the confirmed savings allocation. Then use that Budget assessment to evaluate all my saved goals together, including required monthly contributions and the shared-pool shortfall. Keep recorded totals distinct from complete household expenses.

Expected: **S + B + G**, with **B -> S** (`transaction_category_totals`) and **G -> B** (`monthly_savings_capacity`). The recorded totals are incomplete household coverage; saved capacity remains the confirmed allocation, and all goals share one monthly pool. The original case 7 remains a reasoning check with conditional Budget-to-Spending consumption in evaluation v2. See [conditional financial dependencies](conditional-financial-dependencies.md).
