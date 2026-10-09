# Recovery fixes following the 8 October reasoning tests

The [9 October local claim recovery](orchestration-local-claim-recovery-2026-10-09.md)
supersedes full regeneration for validated local defects, adds independently
reviewed reduced candidates, and preserves safe Compliance metadata at the backend.
The historical descriptions and counts below remain evidence of earlier changes.

The latest [third-retest recovery changes](orchestration-read-only-recovery.md)
separate original draft safety from correction eligibility, extend composition
authority to sealed Education evidence, and add grounded read-only forecasts.
The historical descriptions and verification counts below predate those updates.

The subsequent [retest after 0287740](agent-reasoning-live-test-results-2026-10-08-post0287740.md)
found five further contract/context gaps. See [the follow-on recovery changes](orchestration-post-retest-recovery.md)
for current-message reference provenance, capacity availability, composition consistency,
component repair forecasts and protected claim edits. The checks and live observations
below describe the preceding change set.

The [live run](agent-reasoning-live-test-results-2026-10-08.md) passed 28 of 34 turns.
Five answers were withheld; case 7 produced correct figures but a different valid
conditional graph. The [diagnosis](agent-reasoning-live-root-causes-2026-10-08.md)
distinguishes confirmed defects from explanations that the safe export could not
establish. These changes repair evidence and recovery contracts. They contain no
case IDs, expected answers or prompt-specific routing exceptions in runtime code.

## Writer and reviewer grounding

For Spending, Budget and Goal results with a private financial snapshot, Compliance
receives the same compact server grounding used by the writer. It verifies snapshot
and result-data fingerprints before using that evidence. This includes Goal
`goal_progress`, illustrative `calculation_assumptions`, tool calculations, record
coverage, periods and source qualifications without a second financial field whitelist.
Nonfinancial handoffs and Education retain minimized review fields.

Server-generated references such as `goal_strategy.goal_progress` identify existing
grounding fields. They never establish new facts or permission to retrieve data.

## Owned, bounded correction

Review issues retain a supplied section and brief requirement, and can specify a category,
`qualify`, `complete`, `ground_claim` or `remove_claim`, financial evidence references,
and a zero-based claim range. The server validates references against supplied
evidence and section ownership, and ranges against the affected draft section.
The model never chooses `repairable`.

Citation and qualification issues retain the existing permission and safety gates.
An `unverifiable_claim` category alone remains ineligible. Each such issue must
identify a financial claim range and either removal or grounding from an
existing owned financial reference. Education unsupported claims, prohibited advice,
unsafe wording and unknown required facts receive no new bypass. Removing an
embellishment cannot establish a missing input or complete an unanswered requirement.
The corrected full answer must pass another independent review.

Explicit per-issue categories allow a financial claim correction alongside a separate
owned Education qualification correction. Unclassified issues in a verdict containing
`unverifiable_claim` retain the conservative claim-correction boundary.

Financial defects go to the owning writer; composition defects go to synthesis.
Each receives the identified actions, original rejected text and unchanged grounding.
Rejected text is explicitly untrusted. Synthesis correction now receives authoritative
calculations rather than only narrative summaries. Unaffected tasks stay completed.
Simultaneous owned financial and Education qualification defects can be corrected in
one coordinated round, using each role's separately sealed grounding.

Eligible read-only Spending/Budget/Goal/Education combinations preserve specialist
paragraphs. Adding Spending to the existing preservation path retains its qualifications
and server-verifiable ownership. Rewritten unowned mixed claims do not acquire
specialist authority from model-declared ownership; unsupported ownership still fails
closed. No direct Goal-Spending dependency is added.

Correction remains limited to one round. Existing task attempts, call limits, token
ceilings, known-usage checks and the workflow deadline still apply. A rejected or
unavailable correction cannot release an unreviewed draft. Financial repair traces now
list individual failed predicates instead of only an aggregate denial.

## Semantic spending intent and resolved state

Production routing no longer adds capture because a broad regex matches expense words
inside an explanation. The semantic router chooses analysis versus record/query/forecast
extraction; backend validation and confirmation still control writes. The conservative
recognizer remains for offline fixtures and profile-fact handling, with lookup matches
anchored to the clause start.

When extraction returns `is_spending_request=false`, Spending clears the task capture
flag before grounding. The orchestrator propagates that resolved analysis state,
including when preflight first waits for a dependency. The financial snapshot binds
to the same task used for correction, and repair does not re-enter extraction.
Actual draft handoffs remain excluded from narrative repair.

## Safe diagnostics

Routing completion retains specialist names and requirement flags as safe assignment
metadata; questions, source quotes and amounts are omitted. Review events retain
server-resolved issue owners, action codes, validated evidence references, claim offsets
and a requirement hash. The hash identifies repeated requirements without exposing
wording. Shared trace sanitization rejects unknown ownership and malformed metadata
at each boundary. Private opt-in review files retain their existing redaction, limits
and expiry controls. Safe metadata does not prove every historical veto was incorrect.

## Conditional graph evaluation

Historical `orchestration_live_regression_v1.json` and live verdicts remain frozen.
`orchestration_live_regression_v2.json` retains the 34 original prompts and financial
assertions. For case 7, Goal must consume Budget capacity, while Spending can report
expense pressures independently. Budget consumes Spending when Budget's own assignment
needs recorded expense analysis.

New case 35 explicitly asks Budget to reconcile Spending category totals with saved
limits before Goal uses the Budget assessment. It requires the full chain and retains
the shared-pool numerical assertions. Controlled task-contract tests verify both true
and false `requires_spending` decisions. The current router prompt preserves explicitly
requested data flow while keeping co-selection insufficient to create an edge.
No runtime code reads evaluation expectations. The single current prompt contract
remains the only runtime prompt set.

## Verification and rollout

Regressions cover writer/reviewer parity, modified grounding, identified claim
corrections, invalid/foreign references, invalid ranges, unsafe categories, mixed
ownership, coordinated correction, synthesis grounding, capture fallback, semantic
emergency-fund routing and conditional dependency flags. Shared tests exercise safe
metadata across storage/viewer sanitization.

Offline checks establish application contracts, not deployed-model acceptance.
Release and a fresh signed-in browser run are required to establish whether the five
withheld answers recover consistently. Case 35 is a separate additional demonstration
prompt; the original catalog remains available for historical comparison.

Final local verification on 8 October 2026:

| Check | Result |
|---|---|
| Full AI regression suite | 1,825 passed; one skipped |
| Shared trace/language checks | 50 passed |
| Backend trace persistence checks | 24 passed |
| Decision trace viewer checks | 15 passed |
| LLMSecOps offline evaluation gate | All eight datasets passed: 87 cases |
| Ruff, Chinese source-code scan, Git whitespace checks | Passed |

The synthesis citation/injection tests explicitly exercise the model-synthesis branch
even when production can preserve specialist paragraphs. Separate recovery tests
exercise preservation, so safety coverage remains present for both paths.
JUnit files and the complete evaluation report remain under the local `artifacts`
directory. [Verification metadata](evaluation-evidence/orchestration-review-recovery-2026-10-08.json)
records the check counts and current prompt identity. Changes are local and not deployed.
