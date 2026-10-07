# Conditional financial dependencies

Implemented locally on 7 October 2026 in prompt set **v9**. The signed-in application's
review prompts have not been executed. Deployment and live model routing acceptance remain pending.

## Behavior

Existing goal capture, illustrative calculations and emergency-fund grounding retain their
specialized contracts. The rules below describe ordinary saved-goal reasoning.

| Request | Expected dependency |
|---|---|
| Remaining saved-goal balances, percentage progress, equal monthly contributions | Goal alone; income and Budget are unnecessary |
| Personal affordability, whether goals can be funded or reached, on-track assessment | Goal requests required Budget `monthly_savings_capacity` |
| Mixed Goal arithmetic and feasibility | Required Goal → Budget dependency remains |
| Spending-informed funding assessment | Goal → Budget → Spending |
| Independent Spending analysis and Budget explanation/capacity question | Parallel candidates; no Budget → Spending edge merely from a keyword elsewhere |
| Independent Spending, Budget explanation and saved-goal arithmetic | Parallel candidates; no specialist dependency required |

No direct Goal–Spending edge is added. A two-agent dependent Spending–Goal feasibility case is
still unsupported. The relevant provider chain remains part of the orchestration demonstration.

## Implementation

Goal uses the strict boolean `GoalInputRequirements.requires_capacity` contract. The versioned
classifier examines only the Goal portion of the current question and its resolved follow-up.
Saved records establish arithmetic inputs; their presence does not establish a need for capacity.
Any funding-feasibility part requires capacity, and ambiguous funding assessments classify
conservatively. Invalid classifier output follows the existing bounded schema-validation behavior.

The orchestrator determines and caches this requirement on the Goal task during initialization.
It informs an already selected Budget task of the actual capacity requirement, allowing reuse
without requiring income merely because Goal is selected alongside a conceptual Budget question.
A dynamically requested Budget provider still computes capacity. Resume/retry task copies retain
the classification; they do not repeat it simply to resolve a provider output.
The trace records `task.capacity_requirement.evaluated` with
`GOAL_FEASIBILITY_REQUIRES_CAPACITY` or `GOAL_CAPACITY_NOT_REQUIRED`, explaining the
decision before dependency execution.

Goal arithmetic grounding carries deterministic projections and progress calculated from saved
targets and balances. It carries no affordability result or unsolicited capacity. The narrative
contract omits irrelevant income, capacity-source and budget-month questions for this path.
Non-SGD amounts still require clarification; no conversion is introduced.

Budget no longer creates the optional Spending request from a whole-message keyword test under
v9. The existing typed dependency planner evaluates the relationship between Budget's own work
and recorded expense context. Capability options retain their required fields and optional status;
the model cannot grant itself a new provider, broaden fields or make the optional edge required.
Role-scoped Budget income classification also excludes independent Goal arithmetic and Spending.

This is semantic intent classification, not a guaranteed graph encoded in natural-language wording.
Routing may select additional specialists. An exact parallel result requires no relevant dependency
edges and overlapping ready-task execution, not simply a multi-agent result list.

The v8 Education grounding, hybrid evidence modes, scoped review and bounded repair contracts are
retained in v9. Archived prompt catalogues retain their broad saved-goal policy for pinned evaluations.
The active source default, local development configuration, deployment template and smoke assertions
target v9. Changing the template does not deploy it or restart running services.

## Verification

`tests/test_conditional_financial_dependencies.py` covers saved arithmetic without income,
progress percentages, required feasibility, mixed requests, independent parts, provider reuse,
semantic paraphrases and an actual three-task concurrency barrier. Existing dynamic dependency,
saved capacity, budget reasoning, Education and Compliance suites verify the established chain
and output review behavior. The offline fixture uses isolated conservative recognizers;
production classifiers and planners continue using typed model decisions.
The combined Goal, Budget, Spending and Education regression completes within the existing
six-round limit; this limit has not been increased.

Verification on 7 October 2026:

| Check | Result | Evidence |
|---|---|---|
| Full AI service suite | 1,833 passed; one platform-related skip | [Verification summary](evaluation-evidence/conditional-financial-dependencies-v9.json) |
| Infrastructure selection, model policy, smoke and release checks | 85 passed | [Verification summary](evaluation-evidence/conditional-financial-dependencies-v9.json) |
| Existing offline dependency and routing datasets | 14/14 dependency cases and 6/6 routing cases passed | [Evaluation results](evaluation-evidence/conditional-financial-dependencies-v9.json) |
| Ruff and Git whitespace checks | Passed | Local checks |

These results verify offline contracts. They do not measure the deployed model's routing
accuracy or conversational answer quality. The Windows test harness required execution outside
the sandbox; test temporary files were kept in the project's artifacts directory.
Full JUnit reports remain local under `artifacts/agent-reasoning-demo-20261007/`.

The updated [review prompts](agent-reasoning-test-prompts-2026-10-07.md) now use saved-goal arithmetic
for single Goal and independent multi-agent cases. The profile records and expected shared-pool
shortfalls are unchanged. Live tests require deployment and the user's review of those prompts.

## Code

- `app/agents/goal_strategy.py`: requirement classification, conditional input/dependency checks and arithmetic grounding.
- `app/agents/budget.py`: scoped optional Spending selection and Budget input classification.
- `app/orchestrator.py`: cached requirement shared with preselected capacity providers.
- `app/core/schemas.py`: private task classification cache.
- `app/models/dependency_fixture.py`: offline-only test decisions.
- `prompts/v9/prompts.json`: new Goal requirement contract and scoped planner/writer instructions.

Paths above are relative to `apps/ai-service`.
