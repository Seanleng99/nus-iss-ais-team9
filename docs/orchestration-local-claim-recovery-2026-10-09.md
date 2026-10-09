# Local claim recovery following the 9 October retest

The [live retest](agent-reasoning-live-test-results-2026-10-09.md) matched the
expected financial specialist selection and dependency edges in all 42 turns,
but answer acceptance failed in several turns. The
[root-cause diagnosis](agent-reasoning-live-root-causes-2026-10-09.md) separates
confirmed implementation defects from claim identities that the private-draft-free
export could not establish. This change addresses correction, composition and
diagnostics. The recorded live outcomes remain unchanged.

## Correct identified claims without regenerating the answer

An allowed, repairable review with validated, nonoverlapping local claim ranges
now takes a replacement path before legacy full writer recovery. The model
receives the original question, current answer, server-owned section metadata,
review requirements and unchanged sealed financial/Education grounding. It
returns only an `issue_id` and replacement for every supplied issue. It cannot
return offsets, an entire regenerated summary or arbitrary extra fields.

The server applies replacements to its original ranges. Every character outside
those ranges is preserved by construction. Empty text is permitted only for
`remove_claim`; identity mismatches, overlaps, invalid sizes and foreign citations
are rejected. Topic-label corrections preserve the displayed option number and
single-line structure. Canonical topics and ordered subject metadata remain
unchanged, while the independent reviewer judges the corrected label's meaning.
This permits clarification of an app-generated heading such as a broad fund label
without requiring the Education writer to change its canonical topic identifier.

Presentation summaries and Education display ranges move with the replacements.
Generated limitation/model-knowledge presentation is updated where it has an
unambiguous mapping; verified financial data, sources, coverage authority and
private grounding seals remain fixed. No financial specialist, query planner,
retriever or dependency task is rerun for a local correction. The complete
corrected answer still receives a new Risk & Compliance review.

`answer_correction` is a model call role used by the orchestrator, not another
router-selectable domain agent or a new dependency edge. Its low-reasoning,
1,200-output-token policy is synchronized across the packaged role policy,
local example environment and AWS bootstrap configuration. Production
replacement wording remains model-generated; scripted gateways are offline
contract fixtures.

## Fit recovery inside the existing resource limits

Local repair admission forecasts one replacement/reviewer pass from observed
provider durations, rather than requiring two complete regeneration/reviewer
passes to fit before beginning. During replacement generation, the writer's
deadline reserves observed reviewer time. A bounded contract retry may run only
inside that remaining writer window. Actual gateway token/call controls and the
original workflow deadline remain authoritative; a forecast never guarantees
that provider latency will fit.

Known usage, token growth and call reserves are still checked. Default limits
remain 85 seconds, 20 model calls and 80,000 model tokens. Whole-answer or
completeness issues without independently located local ranges retain the existing
bounded writer/composition paths and their conservative forecasting.

## A reduced answer must receive its own review

If an eligible local correction is unavailable or still blocked, the orchestrator
can construct one reduced candidate by removing complete affected paragraphs.
This requires an unambiguous mapping from specialist presentation to the answer
and sufficient budget for another independent review. Deletions crossing summary
boundaries also remove the rejected presentation from those summaries.

The candidate includes a localized explanation that some requested parts are
withheld. Risk & Compliance reviews the complete reduced answer with the same
verified evidence and current question. Only an unblocked verdict permits release.
A prohibited request, unresolved required input, unavailable authority, exhausted
budget or unverified/blocked review still withholds the response. This path does
not release sections by assuming their earlier draft was safe.

A released reduced answer records `partial_answer=true` and
`answer_status=incomplete`. Stored option referents are cleared so a removed or
renumbered presentation cannot establish the subject of a later ordinal follow-up.
Successful full corrections keep the original validated subjects.

## Correct arithmetic and prevent stale limitations from returning

Spending trend `direction` now follows the exact movement of rounded monetary
amounts: lower is `decreased`, higher is `increased`, and equal cents are `stable`.
The separate significance field still measures change magnitude. Spending and
Compliance instructions explicitly distinguish a small movement from equality.

The generic Education limitation describes what retrieved material establishes,
preserving supported portions instead of asserting that the entire knowledge base
lacks an answer. The reviewer assesses source coverage and completeness per part,
consistent with the existing EV-06 policy. During legacy composition correction,
postprocessing does not restore old uncertainty/gap text from unchanged specialist
metadata. Local replacement correction never reruns that postprocessing.

## Preserve safe diagnostics across the backend boundary

The backend's blocked-result sanitizer retains only allowlisted Risk & Compliance
categories, reason codes, policy-family clause references and permission/completeness
booleans. It still removes private reviewer prose, rejected text, financial data and
other specialist payloads. Protected-text failures and replacement-contract
failures have fixed validation codes. Content-free trace events identify correction
admission, unavailability and the reduced candidate's review admission.

## Current contract and verification

The app and executable evaluations continue using the one current **v10** catalog;
effective instruction changes produce a new prompt content hash automatically.
There are no historical prompt branches, case-specific routes or expected-answer
lookups in production. Conditional financial dependencies and the deferred direct
Goal–Spending edge retain their existing behavior. Policy corpus contents and pins
are unchanged by this recovery update.

Regression coverage checks exact financial movement, app-rendered headings,
unchanged surrounding prose and evidence, invalid replacements, unchanged option
numbers, call/token/time exhaustion, unknown usage, prohibited requests,
independent second/partial reviews, removed-gap postprocessing and safe backend
metadata.

| Offline check | Result |
| --- | --- |
| Full AI service suite | 1,927 passed; one platform skip |
| Full shared localization/trace suite | 64 passed |
| Backend Compliance/trace/storage regressions | 23 passed |
| Frontend trace viewer and coach language | 32 passed |
| Release pins, model role policy and test selection | 38 passed |
| Evaluation gate | 87/87 cases passed across eight suites |
| Ruff, language-source scan and whitespace | Passed |

[Retained verification metadata](evaluation-evidence/orchestration-local-claim-recovery-2026-10-09.json)
identifies the current prompt hash, role policy and test results. Windows HTTP/UI
and Git Bash checks used approved execution outside the sandbox. These checks
test contracts and scripted behavior; deployment and repeated live-model testing
are still required to assess answer quality and consistency.
