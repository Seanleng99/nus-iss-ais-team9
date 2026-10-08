# Recovery after the second 8 October live retest

The subsequent [retest after dae539d](agent-reasoning-live-test-results-2026-10-08-postdae539d.md)
exposed further read-only routing and recovery gaps. See [the third-retest recovery changes](orchestration-read-only-recovery.md)
for semantic operations, reserve context, forecast evidence, Education composition
authority and independent correction eligibility. The observations and verification
counts below describe the preceding change set.

The [live retest after 0287740](agent-reasoning-live-test-results-2026-10-08-post0287740.md)
completed 34 original turns: 29 passed the current conditional acceptance criteria.
Cases 5, 17, 19, 20 and 25 failed; additional full-chain case 35 also failed.
These source changes address the five underlying contract and context gaps.
The recorded live outcomes remain unchanged. A deployed-model retest is still required.

## References within the current question

The router classifies `reference_scope` as `none`, `current_message`, `dialogue` or
`ambiguous`. A same-message reference requires `reference_quote` and
`reference_subject_quote`: unique, nonoverlapping exact spans in the current user text.
Semantic classification establishes their relationship; the server verifies provenance.
The quotes are conversational context, never authority for amounts, records or writes.

A validated `current_message` classification supersedes the preliminary regex resolver.
It keeps the specialist task split and produces
`SEMANTIC_CURRENT_MESSAGE_REFERENCE`, rather than replacing an explicit compound
question with an Investment clarification. Genuine dialogue references retain their
existing source-position, option-identity and history boundaries. A missing historical
option still clarifies. All effective routes reconcile task owners after overrides;
new server-required roles receive the unchanged original request, matching the existing
task fallback. Removed specialists cannot leave stale assignments in the completed route.

## Capacity availability and conditional dependencies

The semantic router sees the saved capacity source and its month. Budget's dependency
planner receives a compact `available_inputs` description: source, per-month availability,
saved-limit presence and whether it provides Goal capacity. Private amounts and raw
records are unnecessary for this planning description.

`requires_spending` controls which capability may be offered. It does not command the
planner to consume an offered capability. A matching confirmed allocation already supports
capacity arithmetic. An actual-versus-plan reconciliation can still consume Spending totals.
The planner decides from Budget's own assigned question and available inputs; transaction
presence alone is insufficient. Missing months remain unavailable, and confirmed capacity
from another month cannot be substituted. Registry authorization and provider reuse remain
in force. The direct Goal–Spending edge remains deferred.

## Local limitations and combined-answer consistency

Specialists distinguish evidence absent from their own scope from evidence absent for
the request. Spending is told when Budget separately owns limit comparisons; it keeps
recorded-amount, pattern and coverage explanations without claiming the application
lacks Budget limits. It does not receive private Budget amounts to make those comparisons.

Normal model synthesis receives `verified_grounding`, using the same sealed financial
evidence contract as review. This is no longer supplied only after a composition veto.
The writer and reviewer instructions explicitly check cross-section consistency in
amounts, dates, capacity sources, evidence availability and qualifications. A composition
defect is attributed to the combined draft with existing supporting evidence references.
Actual missing facts remain missing; the model cannot invent information to reconcile prose.

## Repair cost and headroom

Spending grounding is supplied once in its outer writer payload. The nested model message
contains the request and interpretation instructions, without repeating the same analysis.
Complete financial evidence and source qualifications are retained for both writer and reviewer.

Financial repair forecasts only the latest completed calls for affected writers, the
independent reviewer and any needed synthesizer. Each component accounts for its previous
input, bounded output growth, correction-feedback size and a 25% growth contingency.
This replaces reserving twice every previous input plus maximum output for every role.
`financial.review.repair_estimate` records content-free component estimates before the
aggregate admission decision. Output growth uses the existing Education-repair approach:
1.5 times observed output plus 128, with a 512-token floor, capped by the role output limit.

The forecast is not a guarantee of provider token consumption. Unknown or inconsistent
usage cannot authorize repair. Call limits, deadlines, the configured token ceiling and
the gateway's actual-usage checks still apply to correction and contract-validation retries.
An actual overrun withholds the unreviewed correction. No token limit is increased, and
there is still one semantic correction round followed by independent review.

## Targeted financial corrections

A blocked financial qualification or attribution issue needs a unique exact `claim_quote`
in its affected draft section, or valid explicit character offsets. The server resolves
quotes into owned ranges and verifies any supplied offsets against them. Unsupported or
ambiguous locations fail the existing bounded review-contract correction. Foreign evidence
references cannot acquire another specialist's ownership.
This location requirement also applies to qualification or attribution issues in a mixed
verdict containing an unverifiable claim; that extra category does not permit a broad rewrite.

For specialist correction, global draft offsets are translated into ranges within the
original summary. Generated changes outside those ranges are rejected, including altered
amounts or unrelated caveats. Composition correction similarly protects unaffected draft
text when every issue has a validated location. Completeness without an existing claim
retains the bounded completion path; removal never establishes missing data or answers a
previously unanswered requirement. The immutable grounding snapshot and full second review
remain authoritative. Neither a permitted patch nor a repairable verdict releases a draft.

Case 25's safe export establishes that its previous correction failed the second review,
but does not reveal the exact rejected prose or prove that its reviewer was wrong. These
changes improve correction precision and preserve reserve-guidance attribution. Existing
opt-in private diagnostics remain the way to compare rejected claims with full passages;
claim quotes and rejected prose are excluded from public trace metadata.

## Verification and limits

`test_post_retest_recovery.py` covers paraphrased current-message references, fabricated,
overlapping or repeated antecedents, stale assignments, ignoring an unnecessary Spending hint while retaining
requested reconciliation, verified synthesis facts, unchanged financial amounts, rejected
patches, malformed claim locations, mixed verdicts and a failed second review. Metered OpenAI-contract tests simulate a 53,119-token
first pass: an admissible correction fits the remaining 80,000-token ceiling, a smaller
ceiling denies it, unknown usage denies it, and an actual overrun retains the original veto.
No external model connection is used in those tests.

Local verification on 8 October 2026:

| Check | Result |
| --- | --- |
| Complete AI-service suite, from the CI service directory | 1,849 passed; 1 Windows symlink-permission skip |
| New recovery regressions, included in the full suite | 24 passed |
| Focused existing review/repair and recovery regressions | 170 passed |
| Shared contracts and calculations | 50 passed |
| CI agent-test selection | 23 passed |
| LLMSecOps fixture gate | 87 cases across 8 datasets passed |
| Authored passage retrieval and scope benchmark | 100 cases passed; generated answer quality not measured |
| Ruff, Chinese code scan and diff whitespace checks | Passed |

The full suite was run outside the Windows sandbox because its local socket-pair
restriction stalled FastAPI's test client. Four initial repository-root failures were
relative dataset paths; the service-directory invocation used by CI passes without
application changes. See the [aggregate verification evidence](evaluation-evidence/orchestration-post-retest-recovery-2026-10-08.json).

Changes use the single packaged `prompts/current` contract. Its content hash changes;
no historical prompt selector, test-case ID, canned financial answer, routing phrase
exception or new financial dependency is added. Controlled fixtures prove contracts and
resource boundaries; they do not prove that deployed semantic decisions or repaired prose
will pass consistently. Retest the deployed build with the original prompts and paraphrases.
