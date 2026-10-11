# Conditional financial dependencies

The single packaged [current prompt contract](current-prompt-contract.md) is labelled **v10**. Models classify the task's meaning; the capability registry and orchestrator enforce authorization, required inputs, evidence scope, scheduling and budgets. A prompt label does not switch dependency behavior.

## Behavior

| Request | Expected dependency |
|---|---|
| Remaining saved-goal balances, percentage progress, equal monthly contributions | Goal alone; income and Budget are unnecessary |
| Personal affordability, whether goals can be funded or reached, on-track assessment | Goal requests required Budget `monthly_savings_capacity` |
| Mixed Goal arithmetic and feasibility | Required Goal → Budget dependency remains |
| Spending-informed funding assessment | Goal → Budget → Spending |
| Budget reconciliation of recorded expenses against saved limits | Budget requires Spending `transaction_category_totals` |
| Independent Spending analysis and conceptual Budget explanation | Parallel candidates; no Budget → Spending edge merely from a keyword elsewhere |
| Independent Spending, conceptual Budget and saved-goal arithmetic | Parallel candidates; no specialist dependency required |

The direct Goal–Spending capability remains deferred. A dependent request linking Spending and Goal feasibility can therefore include Budget as the intermediary. Saved-goal capture and emergency-fund assessment retain their separate contracts.

## Goal capacity requirements

The typed `GoalInputRequirements.requires_capacity` decision examines the Goal portion of the current question and its resolved follow-up. Saved records establish arithmetic inputs, while any personal funding-feasibility part requires capacity. Ambiguous funding assessments classify conservatively. The orchestrator caches the requirement on the task and shares it with an already selected Budget provider, so matching capacity can be reused. Resume/retry copies preserve the decision.

The trace records `task.capacity_requirement.evaluated` with `GOAL_FEASIBILITY_REQUIRES_CAPACITY` or `GOAL_CAPACITY_NOT_REQUIRED`. Goal arithmetic carries deterministic remaining amounts, progress and contributions, without unsolicited affordability conclusions. Non-SGD amounts require clarification; no conversion is performed.

Confirmed monthly planning settings supply the chosen savings allocation as one shared pool. Unallocated income is separate. Each requested month is assessed independently; a period total is never substituted for a recurring monthly pool. A missing explicitly requested plan remains unavailable. Fallback capacity needs income and explicit recurring-obligation terms and carries its qualifications.

## Budget consumption of Spending evidence

The router supplies an attributed assignment and requirement fields for each specialist. Budget's planner assesses Budget's own question against scoped or historical recorded expenses; an independent Spending question does not force an edge. A false `requires_spending` router hint does not veto consideration of an available approved capability. Co-selection alone never establishes dependency.

For ordinary reasoning, Spending is optional. A confirmed allocation can supply capacity arithmetic without recorded totals; assessing observed pressure on that allocation can still consume Spending. The typed `operation=reconciliation` requires the totals capability and rejects a readiness decision that did not consume it. The model selects the semantic operation; the server validates its consequences.

Capability fingerprints include dates, historical records and scoped aggregates. The orchestrator reuses only compatible results, detects cycles, resolves required providers before resuming requesters and bounds dependency rounds, retries, time, calls and tokens. Required failures fail closed. Optional failures preserve useful calculations with visible limitations.

## Education dependencies

Budget and Goal may request `education_context` only for validated allowlisted topics relevant to their assigned work. Investment Education alone can execute `education_retriever`; the orchestrator invokes its grounding logic as the tool provider. Requester questions and fingerprints retain scope. Identical evidence is reused within the run. An independently selected Investment specialist normally owns the conceptual explanation, avoiding duplicate optional retrieval; Goal's emergency-fund evidence remains required. Spending stays retrieval-free.

Budget/Goal education needs verified RAG evidence. Optional missing support preserves their financial calculations and reports an education gap. Investment Education has a separately labelled, restricted model-knowledge supplement; that permission does not transfer to other specialists. Independent Policy review remains mandatory for ordinary answers.

## Verification and acceptance

Current executable contracts are covered by `apps/ai-service/tests/test_conditional_financial_dependencies.py`, dynamic-dependency, saved-capacity, Budget reasoning, Education and Compliance suites. They exercise missing income, saved arithmetic, mixed requests, provider reuse, semantic paraphrases and a real task-concurrency barrier. Fixture tests verify deterministic contracts, not production-model accuracy.

The [latest retained live retest](agent-reasoning-live-test-results-2026-10-09-post7356713.md) reports matching specialist sets and dependency edges for all 42 turns at build `7356713`: 30/34 original answers passed, case 35 passed and 6/7 planned repeats passed. Five withheld/incomplete answer outcomes failed. That run predates subsequent source changes and does not establish acceptance of the current effective prompt hash.

Use [current orchestration](orchestration-current-implementation-2026-10-07.md), [the reasoning prompt catalogue](agent-reasoning-test-prompts-2026-10-07.md) and `app.evals.orchestration_acceptance` for graph, overlap, numeric and answer-coverage checks. The frozen historical datasets remain revision-specific test inputs. Complete current acceptance needs repeated real-model evaluation and review; no graph is guaranteed solely by natural-language wording.

## Code

- `apps/ai-service/app/capabilities/registry.py`: requester/provider authorization and required inputs.
- `apps/ai-service/app/agents/goal_strategy.py`: conditional capacity, saved arithmetic and Goal grounding.
- `apps/ai-service/app/agents/budget.py`: scoped optional/required Spending selection and capacity.
- `apps/ai-service/app/orchestrator.py`: assignments, cached requirements, fingerprints, scheduling and reuse.
- `apps/ai-service/app/core/schemas.py`: typed tasks, decisions and capability outcomes.
- `apps/ai-service/prompts/current/prompts.json`: scoped planner/writer instructions.
- `apps/ai-service/app/models/dependency_fixture.py`: offline-only planning decisions.
