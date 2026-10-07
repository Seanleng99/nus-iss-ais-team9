# Live agent reasoning test results — 7 October 2026

**The deployed v9 application demonstrates working routing, conditional Goal dependencies, provider reuse and parallel execution, but it has not passed live acceptance.** Budget still adds Spending to some independent questions, six approved turns timed out, seven answers were withheld, and two explicit education requests became unnecessary clarification.

All **34 approved prompt turns** were attempted through the signed-in Edge application, with **two additional retests** (36 total submissions). The first run started at 18:39 SGT; the last started at 21:08 SGT. Authentication interrupted collection of case 28; after the user signed back in, its saved answer was recovered without resubmitting it. The longer wall-clock interval includes this interruption and evidence capture, rather than continuous model execution.

The active profile was **Agent Reasoning Demo — Synthetic**, `agent-reasoning-demo-20261007`, with October 2026 selected. The live trace metadata identified prompt set **v9**, provider **OpenAI**, and model **gpt-6-luna**. No CRUD prompt was submitted and no budget, spending or goal record was edited. An Overview read after reauthentication still showed income 6,500, October recorded expenses 3,575, planned savings 1,600, unallocated income 950, and the four original goal balances. All figures in this report are SGD.

## Outcomes and interpretation

| First attempts only | Turns |
|---|---:|
| Substantive answer, including answers with graph or coverage gaps | 18 |
| Expected clarification in a fresh chat | 1 |
| Unnecessary clarification | 2 |
| Review withheld the answer | 7 |
| HTTP 503; durable trace confirmed `AI_SERVICE_TIMEOUT` | 6 |
| **Total approved turns** | **34** |

The two retests produced substantive answers: 12R succeeded after case 12 was withheld; 14R reproduced case 14's unwanted dependency. These outcomes are retained separately rather than replacing the first attempts. A useful answer does not establish the expected graph, and a correct graph does not establish a useful answer.

Notation: **S** = Spending, **B** = Budget, **G** = Goal Strategy, **I** = Investment Education. `G → B` means Goal requests Budget's capability; provider data returns to Goal. Education retrieval is a tool dependency and is excluded from the four-specialist count. Mandatory Compliance review is also excluded. Initial routing and final specialist sets are listed separately.

“None saved” describes the visible trace. For an interrupted run it does not guarantee that no later edge could have been requested. Overlapping initial execution alone does not establish independence: requesters can do preflight work and then wait for a provider.

## The twelve requested scenarios

| Case | Expected | Initial → final specialists | Saved edges | Answer / verdict | Reference ID |
|---|---|---|---|---|---|
| 1 | S; no edges | S → S | None saved | Withheld | `b1613cbb-14b4-42f3-9fe5-4794da3c9684` |
| 2 | B; no edges | B → B + S | B → S | Answer correct; graph failed | `8a7e0cd5-84a2-41c2-a7be-7a112d53c4f1` |
| 3 | G; no edges | G → G | None saved | Pass | `f4d6fa81-db9b-4b83-9677-ed6ae151ae10` |
| 4 | I; no edges | I → I | None saved | Pass | `5e989e3f-f836-44f8-9bed-e45533645a42` |
| 5 | B + S; B → S | B + S → B + S | B → S | Pass | `de90ba43-ef14-492d-8cf4-cf555775c1b1` |
| 6 | B + G; G → B | B + G → B + G | B → Education tool; G → B; G → Education tool | Withheld; extra tool edges | `32d67cdf-dd44-4dc3-866b-0463d18c4867` |
| 7 | B + S + G; G → B → S | Not captured → B + G + S | B → S; G → B | Timed out | `ecc5cc79-2cf4-44ec-b7b8-abb0c9a51034` |
| 8 | S + G intent; final B + S + G chain | S + G + B → B + G + S | G → B; B → S | Final graph and answer pass | `06e5ec50-7362-4728-b2be-c1553e9535c1` |
| 9 | B + S; no edges | S + B → B + S | B → S | Answer correct; independence failed | `dbe4b554-7574-4441-b425-11ee032bd311` |
| 10 | B + G; no edges | B + G → B + G | None saved | Pass | `f559a67e-531f-42ab-807c-4b392f229682` |
| 11 | B + S + G; no edges | S + B + G → B + G + S | None saved | Timed out | `b5ffee7d-88b3-468d-b382-5215d8fe19cb` |
| 12 | S + G; no edges | S + G → G + S | None saved | Withheld | `424a1643-07f7-4e08-96c7-ebfec5f892df` |

Case 8 demonstrates the supported three-agent chain, rather than a direct Spending–Goal edge. Budget was already selected by the router, so this run does not demonstrate dynamically scheduling a new Budget provider. The direct edge remains deferred as requested.

## Additional specialist combinations

| Case | Expected | Initial → final specialists | Saved edges | Answer / verdict | Reference ID |
|---|---|---|---|---|---|
| 13 | S + I; no edges | S + I → I + S | None saved | Timed out | `e6436483-c79e-4e1d-9564-aeb67f7a81e0` |
| 14 | B + I; no edges | B + I → B + I + S | B → S | Answer correct; independence failed | `05fb31dd-148c-407a-8368-1525e2d7fe4d` |
| 15 | G + I; no edges | G + I → G + I | None saved | Withheld | `a51990e4-a064-4a9e-a833-8841b3d944b4` |
| 16 | B + S + I; B → S | S + B + I → B + I + S | B → S | Withheld | `1d703d0b-6849-4b81-bdc6-900b465a1f4e` |
| 16P | B + S + I; no edges | S + B + I → B + I + S | None saved | Pass | `f2166dbf-f97e-4942-b6dd-2f281b2ad072` |
| 17 | S + G + I; no edges | S + G + I → G + I + S | None saved | Pass | `914eb584-7b88-4f8f-b69c-9f2e4ced68c8` |
| 18 | B + G + I; G → B | G + B + I → B + G + I | G → B | Pass | `89569a6e-8e77-4058-bb4f-5e7375ff7270` |
| 18P | B + G + I; no edges | B + G + I → B + G + I | None saved | Withheld | `59d057d8-6612-41fa-b601-d0ed9c6aff46` |
| 19 | All four; G → B → S; I independent | S + B + G + I → B + G + I + S | G → B; B → S | Pass | `7863d6c9-4815-4da4-90f5-a0d5221ec6a4` |
| 19P | All four; no edges | S + B + G + I → B + G + I + S | None saved | Timed out | `990d1cd0-e8c4-4748-9c48-48d1b5e29815` |

## Data, follow-up, preference and evidence scenarios

| Case | Expected | Initial → final specialists | Saved edges | Answer / verdict | Reference ID |
|---|---|---|---|---|---|
| 20 | G requires B; add or reuse provider | G + B → B + G + S | G → B; B → S | Answer correct; extra dependency | `ba7a0ea1-a1a0-423a-b3fc-36961dd08791` |
| 21 | S; recurring forecast | S → S | None saved | Pass | `5f0f8836-4b34-4449-b7a3-2b503fb2ba24` |
| 22 | S; November records | S → S | None saved | Partial | `91d50d55-15fb-4547-85f5-26498006cc57` |
| 23 | B + G; G → B; exact months | G + B → B + G | G → B | Pass | `33da1f99-2b8c-4cf0-9448-3cf5496eb0f4` |
| 24 | B + G; G → B; December missing | G + B → B + G | G → B | Withheld | `7c9079f5-4fe7-4257-bc44-adf7e6e57e90` |
| 25 | G; Education tool; emergency-fund path | G + S → G + S | G → Education tool | Timed out; additional specialist | `e22a538a-e72c-4e40-a706-98d29b5f3d79` |
| 26a | I; numbered funds then ETFs | I → I | None saved | Pass with evidence limitation | `7ced08ba-8a57-4eae-9983-49a479ef5ccc` |
| 26b | I; resolve option 2 to ETFs | I → I | None saved | Failed: unnecessary clarification | `8335e04a-b69d-401b-919c-186708c9cf40` |
| 27 | Fresh-chat clarification | I → I | None saved | Pass | `c44152f0-d944-4d2e-a286-99b39034f3ac` |
| 28 | B + G; G → B; compact table | G + B → B + G | G → B; B → Education tool; G → Education tool | Answer/preferences pass; extra tool edges | `32908ca9-92f4-4ccb-96cd-deeca0df3abd` |
| 29 | I; supported education plus tax limit | I → I | None saved | Failed: unnecessary clarification | `59ccbdf1-a774-4f49-ba46-3036eef4bdce` |
| 30 | B + I, or B with Education tool | B + I → B + I + S | B → S | Timed out; extra dependency | `734dc6f5-8fea-4f74-a8e2-9ab0a1d80048` |

## Preserved retests

| Case | Expected | Initial → final specialists | Saved edges | Answer / verdict | Reference ID |
|---|---|---|---|---|---|
| 12R | Retest 12: S + G; no edges | S + G → G + S | None saved | Pass on retest | `2a91ebc0-bea7-4c57-af8f-97361f96b623` |
| 14R | Retest 14: B + I; no edges | B + I → B + I + S | B → S | Answer correct; independence failed again | `d19bd159-94a3-4ba3-862e-0d8d945277a3` |

## What the live traces establish

### Conditional Goal requirements and provider reuse

Case 3 ran Goal alone for saved remaining amounts, progress percentages and equal monthly contributions. It correctly calculated Laptop 500/month, Travel 400/month, Course 500/month and Home Deposit 1,200/month. The trace recorded `GOAL_CAPACITY_NOT_REQUIRED`; it did not add Budget. Cases 10, 12R, 17 and 18P also kept saved-goal arithmetic independent.

Funding questions retained `monthly_savings_capacity`. Cases 5, 6, 8, 18, 19, 20 and 23 saved `reused` resolutions for already selected providers where applicable. Reuse is still a dependency: the requester consumes the matching capability, even when a second provider task is unnecessary. Cases 8 and 20 preselected Budget, so dynamic **Budget addition** remains unproven by this prompt set. Budget's unexpected dynamic **Spending addition** is visible in cases 2, 14, 14R, 20 and 30.

Case 19 is the clearest completed dependency demonstration. Spending finished its first attempt at 14.139 seconds. Budget resumed at 16.323 and finished at 20.959; Goal then resumed at 20.966 and finished at 29.167. Investment ran from 8.496 to 16.315 without an edge connecting it to that chain. The saved edges were exactly `G → B` and `B → S`. Initial Goal and Budget attempts were preflight dependency requests, not completed answers.

### Independent execution

| Case | No specialist edges | Measured common overlap | Final answer |
|---|---|---:|---|
| 10: B + G | Yes | 5.278 s | Useful |
| 12R: S + G | Yes | 5.419 s | Useful |
| 16P: B + S + I | Yes | 7.366 s across all three | Useful |
| 17: S + G + I | Yes | 4.357 s across all three | Useful |
| 18P: B + G + I | Yes | 5.713 s across all three | Withheld |

Case 9 had 6.152 seconds of overlapping first attempts, but Budget requested Spending and resumed afterward. It therefore failed the independent-specialist assertion. Cases 11 and 19P saved the expected specialist sets and no edges, but timed out; they are not completed demonstrations of three- or four-agent independent answers.

### Numerical grounding, recurrence and calendar scope

Useful funding answers correctly kept the **2,600 monthly requirement**, **1,600 October allocation** and **1,000 shortfall** separate from the **950 unallocated planned income** and the Overview's **2,925 income-minus-recorded-expenses** figure. The 1,600 pool was shared across all goals, rather than counted once per goal. Case 23 correctly used September/October/November allocations 1,400 / 1,600 / 1,000 and shortfalls 1,200 / 1,000 / 1,600.

Case 21 forecast only the explicitly recurring rent: **1 November, 1,800 projected**. It distinguished scheduled forecasts from recorded payments and did not infer recurrence from similar descriptions.

Case 22 acknowledged that the records did not support a November-versus-October comparison, but then explained October and September patterns. It should have given a clearer November-specific zero-record result and stated that zero recorded entries do not establish zero real spending. Case 24 withheld the missing-December-budget answer, so useful partial reasoning under missing capacity was not established; the unavailable draft was not inspected or reconstructed.

### Follow-up resolution and answerability

Case 26a displayed two ordered lists: the first used normal numbering for Funds, and the second explicitly had `start="2"` for Exchange-traded funds. Its narrative compared conventional mutual funds and ETFs using visibly labelled permitted model knowledge. Source support was unavailable and explicitly disclosed.

In case 26b, the model router proposed Investment with `exchange-traded_funds`, but the deterministic `FOLLOW_UP_READ_ONLY` override recorded **`AMBIGUOUS_ATTRIBUTED_OPTIONS`**, cleared the topics, and the task returned `needs_input` / `AMBIGUOUS_FOLLOW_UP`. The visible review itself stated that the prior dialogue identified the second option as ETFs and clarification was unnecessary. Nevertheless, the final answer remained “Which goal, option or concept do you mean?” Review marked the incomplete answer non-repairable; no successful repair occurred.

Case 27 asked the identical question in a fresh conversation and correctly clarified. Case 29 explicitly named diversification and current personal ETF tax treatment. The router recognized diversification and ETFs, but `FOLLOW_UP_READ_ONLY` / **`MISSING_SUBJECT`** again cleared the topics and forced clarification. The intended supported-education-plus-tax-scope answer was therefore not exercised. These two failures point to subject-resolution/override behavior, rather than a failure to select the Investment specialist initially.

### Preferences and Education grounding

Case 28 satisfied the requested plain English and compact table while retaining the authoritative 2,600 / 1,600 / 1,000 calculation. It also introduced two optional Education tool edges, from both Budget and Goal, although the prompt requested saved-plan arithmetic. Case 6 had the same extra tool shape. Case 28 ended with a source-support warning unrelated to the numerical task. These additional requests warrant tighter scope checks.

When Investment was separately routed in the completed mixed cases, its citations or model-knowledge labels remained visible, and the captured graphs did not show duplicate Budget/Goal Education retrieval. Case 30 routed Budget + Investment, then added Spending and timed out. It does not prove the alternate controlled Budget-only `education_context` path.

## Unresolved gaps and next checks

1. **Budget dependency scope:** cases 2, 9, 14, 14R, 20 and 30 requested Spending where Budget's own question concerned a confirmed plan or a general concept. Scope the planner to Budget's actual subquestion and retest these exact prompts. The working 16P case shows that independent Budget behavior is possible, but not dependable across these wordings.
2. **Run deadline:** cases 7, 11, 13, 19P, 25 and 30 returned HTTP 503. Each durable trace showed `AI_SERVICE_TIMEOUT`, with saved execution ending at roughly 45 seconds. Inspect model-call latency and the time consumed by dependency discovery, resumption, synthesis and review before changing limits. The UI evidence establishes the timeout code, not an underlying provider/network root cause.
3. **Review withholding:** cases 1, 6, 12, 16, 18P and 24 were blocked under `factual_qualification`; case 15 under `unverifiable_claim`. These are failed user-facing outcomes for permitted reasoning prompts. Withheld drafts were not available through the UI, so this report does not assert that the blocks were false positives. The successful 12R retest warrants a repeatability and review-quality check.
4. **Follow-up overrides:** 26b and 29 selected the appropriate domain and then lost their subject during a deterministic override. Verify the displayed-order contract and locally explicit subjects before forcing clarification. Review recognized 26b's incompleteness but did not repair it.
5. **Period handling and extra grounding:** clarify the zero-record November result in 22, return useful missing-budget reasoning in 24, and avoid irrelevant Education requests/source warnings for 6 and 28.

These checks can focus on the existing router, scoped dependency planner, follow-up resolver and review contracts. This test run does not justify adding the deferred direct Goal–Spending edge or expanding the demonstration with new concepts.

## Evidence and limits

- Approved prompts and exact input expectations: [Prompt catalogue](agent-reasoning-test-prompts-2026-10-07.md).
- Sanitized structured results, exact submitted prompts, reference IDs, edges, resolutions, measured overlaps and assessments: [Live v9 evidence](evaluation-evidence/agent-reasoning-live-v9-2026-10-07.json).
- Successful table screenshot: [Case 28](evaluation-evidence/agent-reasoning-live-v9-case-28.png).
- Raw Coach/trace DOM snapshots and focused rendered-grid captures remain local in `artifacts/agent-reasoning-live-20261007/results.json`; timeline rows are retained for the measured concurrency cases. The signed-in email and browser credentials are excluded from the versioned evidence.

Each Coach reference was opened in the trace viewer. For HTTP failures, the reference was recovered by selecting the corresponding timed-out run using conversation title and submission time, then verifying its full reference ID and failure code. The Recent runs label is **conversation_title**, not a request-text preview (`apps/frontend/ui/trace_viewer.py:671`). A failed first turn can leave its title on a later successful turn; a different title alone is not evidence of a stale trace. Earlier title concerns for 12 and 14 were resolved on this basis and the two retests are preserved.

This is one live sample per approved turn, with two retests. It is not a routing-accuracy estimate. Virtualized tables were read after focusing their UI grids, and relevant timelines were paged through the UI. Empty or unavailable cells were not treated as proof of execution. No direct API call, fixture result, failure injection, or hidden draft was used to produce the live results. Observed successful dependency resumption is not a retryable-error test, and no successful semantic repair is claimed.

The existing 1,833 passing AI-service tests, 85 infrastructure tests and 20 offline evaluation cases remain useful contract checks. The live failures show that those checks alone are insufficient for model-routing and response acceptance. No application code was changed during this testing task.
