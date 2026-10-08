# Conditional financial dependencies

Implemented on 7 October 2026 in prompt set **v9**. The signed-in Edge application's
trace metadata confirmed v9 with OpenAI / gpt-6-luna. All 34 approved prompt turns were
attempted, with two retests. **Live acceptance has not passed**; see the
[live results](agent-reasoning-live-test-results-2026-10-07.md) for the working graphs and remaining gaps.

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

Budget does not create the optional Spending request from a whole-message keyword test. The existing typed dependency planner evaluates the relationship between Budget's own work
and recorded expense context. Capability options retain their required fields and optional status;
the model cannot grant itself a new provider, broaden fields or make the optional edge required.
Role-scoped Budget income classification also excludes independent Goal arithmetic and Spending.

After the second 8 October retest, the router also receives the saved capacity source and
month, and Budget's planner receives a compact description of available capacity and limits.
An offered Spending capability remains optional: the semantic planner may reject an
unnecessary `requires_spending` hint when a confirmed allocation supplies the assigned
capacity calculation. Requested actual-versus-plan reconciliation still consumes Spending.
See [the follow-on recovery changes](orchestration-post-retest-recovery.md).

This is semantic intent classification, not a guaranteed graph encoded in natural-language wording.
Routing may select additional specialists. An exact parallel result requires no relevant dependency
edges and overlapping ready-task execution, not simply a multi-agent result list.

The v8 Education grounding, hybrid evidence modes, scoped review and bounded repair contracts are
retained in v9. Historical behavior is recoverable from Git; executable evaluations use the [single current contract](current-prompt-contract.md).
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
| Signed-in Edge reasoning prompts | 34 approved turns attempted plus two retests; live acceptance failed | [Live results](agent-reasoning-live-test-results-2026-10-07.md) |

These results verify offline contracts. They do not measure the deployed model's routing
accuracy or conversational answer quality. The Windows test harness required execution outside
the sandbox; test temporary files were kept in the project's artifacts directory.
Full JUnit reports remain local under `artifacts/agent-reasoning-demo-20261007/`.

The updated [review prompts](agent-reasoning-test-prompts-2026-10-07.md) use saved-goal arithmetic
for single Goal and independent multi-agent cases. The live runs demonstrated this conditional
Goal behavior, the required funding chain, provider reuse and several independent overlapping
executions. Budget still requested Spending for some independent conceptual or confirmed-plan
questions. Six first attempts timed out, seven were withheld, and two explicit education requests
became unnecessary clarification. These are live-model gaps despite the passing offline contracts.
The profile records and expected shared-pool shortfalls are unchanged. Direct Goal–Spending remains deferred.

## Code

The subsequent [seven live-gap fixes](orchestration-live-fixes.md) add attributed model task assignments before planning, independent Spending calendar scope, workflow deadlines and one bounded financial qualification correction. Model requirement fields can avoid redundant classifiers; unknown legacy single-specialist requirements retain the scoped classifier. Confirmed-plan capacity arithmetic can use saved allocations without raw income. Independent Budget concepts retain their own requirement even when a separate Goal task assesses feasibility. Conditional Education providers receive requester-specific questions and fingerprints. The historical verification table above predates those changes; it is not a new live acceptance result.

The frozen `orchestration_live_regression_v1.json` suite contains all 34 approved turns with graph and financial assertions plus human answer checks. `app.evals.orchestration_acceptance` runs it without `requested_agents` overrides and explicitly separates offline fixture contracts from repeated production-model evaluation. Fixture failures remain visible rather than being tailored to expected routes.

- `app/agents/goal_strategy.py`: requirement classification, conditional input/dependency checks and arithmetic grounding.
- `app/agents/budget.py`: scoped optional Spending selection and Budget input classification.
- `app/orchestrator.py`: cached requirement shared with preselected capacity providers.
- `app/core/schemas.py`: private task classification cache.
- `app/models/dependency_fixture.py`: offline-only test decisions.
- `prompts/current/prompts.json`: Goal requirement contract and scoped planner/writer instructions.

Paths above are relative to `apps/ai-service`.

## Review recovery and graph demonstrations

The [8 October recovery changes](orchestration-review-recovery.md) preserve explicitly requested data flow in model task assignments, retain safe requirement flags in traces and separate a valid conditional decomposition from a full-chain demonstration. Updated evaluation v2 keeps case 7's original prompt and financial checks, makes Budget consumption of Spending conditional, and adds case 35 with an explicit reconciliation step. Historical v1 and browser verdicts remain unchanged. Direct Goal-Spending remains deferred.
