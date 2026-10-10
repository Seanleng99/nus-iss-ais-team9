# Root causes of the 8 October live-test failures

This is the pre-fix diagnosis of the deployed 8 October test run. The subsequent
[local recovery implementation](orchestration-review-recovery.md) changes the evidence,
capture-state and correction paths described below. The pending-deployment statement
reflects this diagnosis’s cutoff; it is not a current deployment-status assertion. The
historical failures are not reclassified.

This diagnosis combines the [live results](agent-reasoning-live-test-results-2026-10-08.md), the official UI profile export, and the current implementation. It distinguishes a confirmed execution cause from a likely explanation of a model verdict. A review category is not, by itself, proof that the model rejected a correct sentence.

## Case-by-case diagnosis

| Case | Confirmed execution cause | Underlying issue and evidence limits |
|---|---|---|
| 3 — Goal arithmetic | Compliance blocks `unverifiable_claim`; derived repair eligibility is false. | Goal's writer receives `goal_progress`, but the reviewer filters that field out. This is a confirmed evidence handoff defect and a strong explanation for rejecting saved balances/progress as unverifiable. The exact rejected sentence is not retained in the safe export. |
| 5 — Budget + Spending | Expected B → S works. Review blocks `factual_qualification`; one synthesis correction is allowed, but the second review blocks the same category. | The correction did not obtain an accepted qualification. Calls show a synthesis rewrite and re-review, with no specialist regeneration during repair. The one-round correction cannot recover after that second rejection. The exact qualifier/claim and whether the second veto is justified are unavailable in the safe trace. |
| 7 — Full three-agent chain | G → B is present; B → S is absent. Budget completes without a dependency-planner call. Answer figures are correct. | The router decomposes recorded spending and saved-plan capacity into separate responsibilities. Budget's options suppress Spending when its assignment says `requires_spending=false`. The trace pattern supports this explanation, but the assignment itself is not saved in the exported audit. The approved test expects a stronger integrated graph than this decomposition requires. |
| 13 — Spending + Investment | Independent routing and overlap work. Review blocks `factual_qualification`; financial repair is ineligible and Education repair reports `REPAIR_SECTION_NOT_OWNED`. | There is a fragile ownership boundary for rewritten combined answers: only verbatim specialist summaries receive owned review ranges. Spending + Investment always goes through synthesis rather than the existing preservation path. A financial defect cannot be assigned to Education, and an unowned mixed draft cannot use the financial draft repair exception. Exact issue attribution and the individual financial eligibility failure are not saved, so ownership loss is a supported implementation risk, not a fully proven explanation of this particular veto. |
| 15 — Goal + Investment | Review blocks both `factual_qualification` and `unverifiable_claim`; derived repair eligibility is false. | The Goal reviewer evidence gap also applies here. In addition, the presence of `unverifiable_claim` is sufficient to prohibit the bounded qualification repair. The trace does not identify which claim generated each category. |
| 25 — Emergency fund | Model initially selects Goal alone with `spending_capture=false`. Deterministic overrides change capture to true and add Spending. Review later marks the defect repairable, but the financial repair gate excludes all capture runs. | The spending regex matches **“what my recorded expenses”** within an explanation request. That broad lookup/capture classification overrides the semantic route. The Spending extractor falls back to analysis, but the run-level capture flag remains true. This false flag is a confirmed reason repair cannot run. Education repair cannot own the financial defect. |

## Goal writer/reviewer evidence mismatch

[Goal grounding](../apps/ai-service/app/agents/goal_strategy.py) produces `goal_progress` with each saved goal's target amount, current balance and progress percentage for saved-goal arithmetic. The narrative writer receives that grounding. However, the [Compliance payload](../apps/ai-service/app/agents/risk_compliance.py) builds `agent_results.data` from a fixed field list containing `projections` but omitting `goal_progress`.

The reviewer therefore receives remaining amounts, months and monthly contributions, but not the authoritative target/current balances or percentages needed to verify progress claims. A percentage or saved-balance statement can be grounded for the writer while appearing unsupported to the reviewer. A local read-only check confirmed that the reviewer field list includes `projections` and excludes `goal_progress`.

This defect is directly relevant to case 3's requested progress percentages and to any additional balance/progress statements in case 15. Successful Goal answers elsewhere do not eliminate the gap; they show that the model does not reject every answer encountering it. The safe export cannot establish the exact sentence the reviewer disputed.

## Repair eligibility and ownership

The model does **not** return the final `repairable` flag. [Compliance derives it](../apps/ai-service/app/agents/risk_compliance.py) from permission, financial-language safety, issue ownership and categories. Bounded correction admits only `citation_attribution` and `factual_qualification`. Any `unverifiable_claim` blocks eligibility, which explains the lack of correction in cases 3 and 15 even if a claim could be re-grounded or removed safely.

[Review section ownership](../apps/ai-service/app/core/review_sections.py) depends on a specialist's complete summary being a literal substring of the final draft. If synthesis rewrites it, its owned range is absent and the reviewer can only identify the broad `draft` section for that prose. Financial draft repair is permitted only when all results have financial grounding and no Investment specialist is present. Education repair requires Education-owned issues. This leaves a recovery gap for some financial defects in mixed rewritten answers.

The [preservation path](../apps/ai-service/app/orchestrator.py) allows Budget, Goal and Investment combinations but excludes Spending. Case 13 therefore has a synthesis call, increasing the risk of losing both qualifications and exact section ownership. Its saved repair denials establish a recovery failure but omit the validated issue list and individual financial gate outcomes needed to isolate the precise ownership/permission/safety predicate.

Case 5 does get a correction: the saved calls after the first review are another synthesizer call and another review. No Budget or Spending writer runs during that correction. The second review still blocks factual qualification, so the application withholds the answer after its bounded repair attempt. This establishes failed correction, but not the actual disputed phrase.

## Deterministic spending-capture false positive

[The capture predicate](../apps/ai-service/app/agents/spending_capture.py) checks a broad question pattern before excluding general explanation questions. Its pattern accepts a question word followed by an expense/spending term anywhere in the clause. For case 25, a local read-only reproduction returns `True` and identifies the matching text as **“what my recorded expenses”**.

The saved trace records the exact cascade:

1. Semantic model proposes Goal only, capture false.
2. `SPENDING_CAPTURE_REQUEST` changes capture to true.
3. `SPENDING_CAPTURE_REQUIRES_SPECIALIST` adds Spending.
4. A `spending_capture` model call runs, then ordinary Spending analysis also runs.
5. Compliance blocks factual qualification but reports derived `repairable=true`.
6. Financial repair rejects the run because the capture flag remains true.
7. Education repair rejects the financial issue's ownership.

The [Spending execution path](../apps/ai-service/app/agents/spending.py) falls back to ordinary reasoning if the extractor decides the request is not a spending-record request; it does not clear the original run flag. The [financial repair gate](../apps/ai-service/app/orchestrator.py) checks that run flag, rather than the final classified operation. No financial record was saved by this path in the test.

## Case 7's graph expectation

Budget's [optional dependency options](../apps/ai-service/app/agents/budget.py) exclude `transaction_category_totals` when its own semantic assignment explicitly has `requires_spending=false`. [Base preflight](../apps/ai-service/app/agents/base.py) skips the dependency planner when there are no options. In case 7, spending records exist, Budget runs normally, and no dependency-planner call occurs; this strongly supports an assignment that scoped Budget to the confirmed savings allocation.

The router's recorded rationale separately assigns expense pressures to Spending and saved capacity to Budget. Goal consumes Budget capacity. That graph can answer the question correctly without Budget consuming Spending's specialist result. It fails the frozen catalog's full-chain expectation, but it is not an execution failure or incorrect savings calculation. Cases 8 and 19 still demonstrate the full chain. Forcing a Spending dependency on every compound question would undermine the conditional design.

## Diagnostic limitation

The public/exported blocked trace removes generated drafts, specialist data and detailed review requirements. It retains categories and aggregate repair reason codes. Financial eligibility failures are recorded as `FINANCIAL_REPAIR_NOT_ELIGIBLE` rather than the individual failed checks, and router task assignments are excluded from the saved turn decision. These omissions limit how precisely cases 5, 7 and 13 can be attributed. Claims that a specific missing caveat or sentence caused them would require private diagnostic evidence; they are not established by the current safe export.
