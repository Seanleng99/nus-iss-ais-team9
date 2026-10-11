# Risk & Compliance review update — 9 October 2026

The subsequent [local claim recovery](orchestration-local-claim-recovery-2026-10-09.md)
addresses correction and partial-review failures found in the deployed v10 retest,
and fixes backend sanitization of safe review metadata. The scope and verification
counts below describe the original Risk & Compliance update. The later
[post-recovery browser retest](agent-reasoning-live-test-results-2026-10-09-post7356713.md)
retains five failed answers; current controls and their remaining limits are in
[security guardrails](security-guardrails.md) and [Policy governance](policy-rag-governance.md).

Permitted requests previously received the same generic verification message
whether a generated claim needed qualification or the reviewer failed its own
contract. Blocked results discarded useful reason metadata, and the viewer hid
policy provenance. Optional Education-gap results returned before receiving a
financial grounding snapshot, so their review lost the scoped contract.

## Resulting behavior

- The application renders reviewed English/Chinese explanations from validated
  reason categories. Technical review failure and unavailable policy evidence
  receive their own explanations. Neither establishes prohibited user intent.
- Public withheld Compliance results retain allowlisted codes, permission and
  completeness booleans, and relevant policy-family clause references. They do
  not retain private reviewer wording, rejected drafts or financial facts.
- Structured generation records JSON versus schema failure. Scoped review also
  records category mismatch, unknown section, missing/non-unique claim, offset
  mismatch, foreign evidence reference and invalid range. Education query-plan
  validation records its failed predicate without changing planning decisions.
- Financial evidence-gap results receive the same sealed authority as normal
  financial results. Independent review receives the unchanged available facts
  and empty Education evidence honestly, and uses the scoped contract. The change
  does not create source support or release an unreviewed answer.
- Blocked trace views display safe reasons, relevant clause IDs and Education/
  Policy provenance, including checksum and review date. Model-call views expose
  the fixed validation reason. Historical traces without these fields still work.

The three Policy documents now define permitted coaching, owned app operations,
investment/account boundaries, evidence modes and authority, partial coverage,
financial meanings, recurrence, shared goal funding, combined answers,
conversation/preferences, authorized handoffs and privacy-safe diagnostics.
Their version is `financial-coach-policy-sg@2026-10-09.1`. The one current prompt
catalog is labelled v10 and uses the supplied Compliance schema instead of its
old minimal JSON example. There are no prompt-version branches or new routing
rules. Offline Policy fixtures reuse the same document meaning.

## Limits and rollout

Semantic routing, factual judgment and correction instructions remain model
decisions. Fixed reason text describes accepted verdict categories; it does not
publish the model's private explanation or prove that a reviewer was correct.
Policy-clause references identify relevant rule families rather than exact
claim-to-clause attribution. Invalid contracts remain fail-closed, and valid
corrections still require another independent review within existing limits.

This scope does not change financial routing, the deferred direct Goal–Spending
edge, backend forecast-template composition, model choice or workflow deadlines.
It therefore does not claim to resolve all seven previous live failures. The
existing frozen live reports remain historical evidence.

The manifest and deployment template were updated together in this 9 October change, committed as
`45ea010`; the follow-on local claim-recovery work is recorded as `7356713`. Release loads the
manifest's policy pin and the current prompt identity. This report does not establish deployment of either
commit; consult the separately dated live reports for deployment and acceptance evidence. Active
model-comparison and user-study configuration, the user-study template, smoke
fixtures and current architecture/orchestration docs now match v10. Deployment
and application defaults derive their prompt identity from the current manifest.
Frozen v9 reports retain the version actually observed.

## Offline verification, 9 October 2026 SGT

| Check | Result |
| --- | --- |
| Full AI service suite | 1,883 passed; one platform skip |
| Full shared suite | 64 passed |
| Backend trace/storage regressions | 22 passed |
| Frontend trace viewer and coach UI | 40 passed |
| Release, smoke, model-comparison and user-study configuration | 99 passed |
| Offline evaluation gate | 87/87 cases passed across eight suites |
| Ruff, packaged-corpus governance, language-source scan and whitespace | Passed |

[Retained verification metadata](evaluation-evidence/risk-compliance-review-update-2026-10-09.json)
identifies the effective prompt hash, policy versions/checksums and test counts.
Windows HTTP/UI and Git Bash test harnesses required approved execution outside
the sandbox. These checks verify local contracts and mocked behavior; they do not
measure production-model review accuracy, routing consistency or answer quality.
