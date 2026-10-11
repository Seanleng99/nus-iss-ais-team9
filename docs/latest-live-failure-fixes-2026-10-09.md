# Latest live-failure fixes — 9 October 2026

Risk & Compliance explanations, diagnostics, policy documents and v10 alignment
were committed separately as `45ea010`. This follow-up addresses the seven
failed cases in the 8 October v9 retest at build `e99409d`. That retired report is
recoverable from Git. The retained [v10 baseline](agent-reasoning-live-test-results-2026-10-09.md)
and [post-recovery retest](agent-reasoning-live-test-results-2026-10-09-post7356713.md)
record subsequent outcomes; this note preserves the original fixes and local counts.

| Case | Observed problem | Follow-up change |
|---|---|---|
| 5 | Budget and Spending ran independently despite the expected observed-pressure relationship | Budget's own semantic planner can reconsider a negative router hint. Available records offer the approved totals capability; the planner still decides whether Budget needs it. |
| 9 | September's calendar window was described as complete records | Historical month rows carry observed first/last dates and unknown completeness. Writer and reviewer distinguish calendar scope from recorded coverage per month. |
| 13 | A corrective review exhausted the workflow deadline | Repair admission now forecasts provider latency, including bounded contract corrections. Quote-based claim location and reduced redundant review fields lower avoidable validation retries. Work that cannot fit remains withheld rather than starting another repair. |
| 21 | Backend forecast replacement/fallback dropped the requested explanation | Every completed backend forecast includes its app-owned meaning: projected schedules do not create payments; linked settlements reduce outstanding obligations. English and Chinese fallback responses preserve that explanation. |
| 25 | An Education query plan failed provenance validation twice; its gap answer was withheld | Provider output schema exposes accepted topic and public concept choices. Privacy/provenance checks remain. The preceding Compliance commit seals financial gap evidence and gives precise validation diagnostics. |
| 29 | The reviewer failed its own contract for a supported explanation plus tax limitation | The reviewer selects a unique exact quote instead of calculating offsets. Owned issue requirements replace redundant `missing_points` wording, while invalid ownership, categories and evidence still fail closed. The exact historical predicate remains unknown. |
| 30 | Budget-only liquidity context was withheld after correction | Budget and review instructions separate financial capacity authority from general sourced concepts. Unverified cash balances/access remain unavailable. A regression exercises Budget-only Education and a freshly reviewed correction with identical capacity and sources. |

These changes apply to contracts and evidence handling, not test prompt strings.
The model still chooses routes, optional dependencies, public subquestions,
semantic support, narratives and policy verdicts. Deterministic safeguards enforce
authorized capabilities, factual calculations, exact provenance, ownership and
resource bounds. The forecast definition is an intrinsic explanation of the
backend operation, not a financial recommendation.

The single packaged catalog remains v10; there are no prompt-version selection
branches. Inline instructions and schemas are implementation changes bound to
the deployed build. Historical v9 evidence is recoverable from Git; the separate
Compliance verification remains retained with its original measurement scope.

## Verification and remaining acceptance

Targeted scripted/offline checks verify both dependent and independent Budget
paths, per-month writer/reviewer coverage, bounded public query choices,
paraphrased completeness feedback, quote-only claim correction, insufficient
repair time, and Budget-only Education preserving its authority across repair.
Backend checks force composition failure after authoritative forecast staging
and verify dates, totals, explanation and unchanged ledger row count.

Verification: **1,892 AI tests passed** with one platform skip; **63 backend
recurrence/composition tests passed**; **64 shared-library tests passed**.
The offline policy gate passed all **87 cases across eight suites**. The authored
RAG retrieval/scope benchmark passed **100/100**; generated-answer quality is not
measured by that benchmark. Ruff, the Chinese code scan and whitespace checks
passed. See [verification evidence](evaluation-evidence/latest-live-failure-fixes-2026-10-09.json).

The old exported traces do not identify every failed semantic reviewer predicate.
These regressions demonstrate contract behavior; they cannot prove that GPT-6
Luna will consistently choose the expected graph or accept every legitimate
answer. At this report’s 9 October cutoff, deployment and fresh signed-in tests, including
repeated attempts, were still required before marking the seven live cases passed.
This records the acceptance status then; later dated reports provide subsequent evidence.
