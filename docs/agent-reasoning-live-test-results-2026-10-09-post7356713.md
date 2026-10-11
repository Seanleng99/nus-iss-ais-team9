# Live reasoning retest — 9 October 2026

**Original turns: 30/34 passed. Full-chain case 35: pass. Planned repeats: 6/7 passed.**

Executed in the signed-in Edge tab with Agent Reasoning Demo — Synthetic and October 2026 selected. All standalone cases used fresh chats; 26b continued 26a. Seven selected cases were each repeated once after the full set; no selective reruns to obtain passes.

All 25 expenses, 3 budgets and 4 goals are exactly unchanged across every exported field compared with the export taken before this run. Only test chats and traces were added.

Acceptance checks the delivered answer, specialist selection, dependency edges, required parallel overlap and numeric assertions separately. S = Spending; B = Budget; G = Goal; I = Investment. Arrows point from requester to provider. Correct numbers alone do not pass a dependency test.

[Selected trace evidence](evaluation-evidence/agent-reasoning-live-v10-2026-10-09-post7356713.json). Raw exports remain private in ignored artifacts.

| Case | Scenario | Selected specialists | Dependencies | Outcome | Reference ID |
| --- | --- | --- | --- | --- | --- |
| 1 | Spending: single specialist | S | None | **PASS** | `99011d15-df18-420f-9b21-0ae2a98d50b2` |
| 2 | Budget: single specialist | B | None | **PASS** | `aed240f3-8e30-43c7-9a8d-d38c91c72d74` |
| 3 | Goal: single specialist | G | None | **PASS** | `22f77194-59bb-40ba-a55e-06b4d172cf2a` |
| 4 | Investment: single specialist | I | None | **PASS** | `191f4729-5a39-4cc4-9f1b-bae8981f1e31` |
| 5 | Budget + Spending: dependency | B + S | B → S (transaction_category_totals) | **PASS** | `1ab2d3f1-8f9f-4292-bf73-83d6b19e929c` |
| 6 | Budget + Goal: dependency | G + B | G → B (monthly_savings_capacity) | **PASS** | `9498bb08-e1ee-4ced-8ec9-2db4e8a878a6` |
| 7 | Budget + Spending + Goal: dependency | S + G + B | G → B (monthly_savings_capacity); B → S (transaction_category_totals) | **PASS** | `d9f30211-fae2-4b9b-91d1-84af3721f70e` |
| 8 | Spending + Goal: dependency requested, exact pair unsupported | S + G + B | G → B (monthly_savings_capacity); B → S (transaction_category_totals) | **PASS** | `b689b91a-1205-4c19-8e02-8b09aed5e346` |
| 9 | Budget + Spending: independent parallel candidates | S + B | None | **FAIL** | `d6bc301d-305d-4371-b5d7-7b430dd35347` |
| 10 | Budget + Goal: independent parallel candidates | B + G | None | **PASS** | `24ea9311-cf4a-4bea-bb0c-b15890740716` |
| 11 | Budget + Spending + Goal: independent parallel candidates | S + B + G | None | **PASS** | `ca52f499-a6b5-4e33-acbd-e45339b795a7` |
| 12 | Spending + Goal: independent parallel candidates | S + G | None | **PASS** | `0cd2c7d3-e256-43dd-81dd-d23a34b8cd41` |
| 13 | Spending + Investment | S + I | None | **PASS** | `fcbbc069-5d71-49c2-9287-66452ba66d95` |
| 14 | Budget + Investment | B + I | None | **PASS** | `a8253e12-7c55-4cdd-9ccf-526893579407` |
| 15 | Goal + Investment | G + I | None | **PASS** | `f190f3cd-8be4-4b34-8536-4f7f19e51ef7` |
| 16 | Budget + Spending + Investment | B + I + S | B → S (transaction_category_totals) | **FAIL** | `828d1218-c811-46ff-a08d-c72681a1c743` |
| 16P | Independent Investment combination | S + B + I | None | **FAIL** | `ebba8026-66dd-4a47-b764-31df3c8b927f` |
| 17 | Spending + Goal + Investment | S + G + I | None | **FAIL** | `ce89b44c-c38d-47a4-bf20-761cc4c18c27` |
| 18 | Budget + Goal + Investment | G + I + B | G → B (monthly_savings_capacity) | **PASS** | `afdb470b-18d2-4715-ab13-922e3efec1b9` |
| 18P | Independent Investment combination | B + G + I | None | **PASS** | `1adc866e-0851-40d3-be79-9c48b36a16f9` |
| 19 | All four specialists | S + G + I + B | G → B (monthly_savings_capacity); B → S (transaction_category_totals) | **PASS** | `7fcc9a1e-d1fa-43d9-86c0-7dd930ac2733` |
| 19P | Independent Investment combination | S + B + G + I | None | **PASS** | `ad17ced7-fc86-4f2b-8cd2-101d35b14420` |
| 20 | Goal dynamically adds Budget | G + B | G → B (monthly_savings_capacity) | **PASS** | `bde75adc-bcdf-490b-826c-f57188758566` |
| 21 | Recurrence reasoning: projected versus recorded expenses | S | None | **PASS** | `bf90d35e-d39b-4f30-a5a1-070596a9ba3e` |
| 22 | Saved plan with no observed expenses | S | None | **PASS** | `e5c16753-54b4-4a83-ac00-f662125ad1a1` |
| 23 | Calendar scope and competing goals | G + B | G → B (monthly_savings_capacity) | **PASS** | `1cfd46a8-5c9a-4406-a5e8-4ca44a0b5349` |
| 24 | Missing requested budget | G + B | G → B (monthly_savings_capacity) | **PASS** | `a24020fb-da9a-46dd-848d-4f554de05729` |
| 25 | Emergency-fund special path | G | G → tool:education_retriever:0cef16ac70dbf3b0 (education_context) | **PASS** | `f7e0416c-874f-426b-81e9-b8a832fbec31` |
| 26a | Follow-up subject resolution | I | None | **PASS** | `fd666761-c0d7-4e82-bbfe-cffa75ee20c0` |
| 26b | Follow-up subject resolution | I | None | **PASS** | `580b00fa-1e35-4ea3-bee8-846795221f31` |
| 27 | Ambiguous follow-up in a fresh conversation | I | None | **PASS** | `5d862f89-200f-4194-afdd-6a4c64b76f0d` |
| 28 | Response preferences without changing reasoning | G + B | G → B (monthly_savings_capacity) | **PASS** | `b1d9820c-f741-4795-ad2d-f50f4288a4a1` |
| 29 | Partial education answerability | I | None | **PASS** | `5f5f199e-f32e-4ac4-9a4d-df8692831c37` |
| 30 | Conditional Education grounding versus a separately routed Investment answer | B + I | None | **PASS** | `5b133e2b-f9a6-4194-ac5a-7241afde9b8f` |
| 35 | Explicit full dependency chain (additional) | S + B + G | G → B (monthly_savings_capacity); B → S (transaction_category_totals) | **PASS** | `137ba816-bab0-488c-8a39-05c9faeac229` |
| 5R | Budget + Spending: dependency | B + S | B → S (transaction_category_totals) | **PASS** | `e9b54b01-4deb-4e94-8280-b10156767e13` |
| 9R | Budget + Spending: independent parallel candidates | S + B | None | **PASS** | `35a2f88c-f316-42ea-8bb6-bb4fd47e6613` |
| 13R | Spending + Investment | S + I | None | **PASS** | `4d35c0c8-2b9a-4375-b17f-a194ea00482e` |
| 21R | Recurrence reasoning: projected versus recorded expenses | S | None | **PASS** | `6971a076-8e66-44d8-8d12-6801e8feff3f` |
| 25R | Emergency-fund special path | G | G → tool:education_retriever:1b6a1a6c1a0f5e3c (education_context) | **PASS** | `6e5cd843-5b2e-4454-bc06-8ddcce9fcc1a` |
| 29R | Partial education answerability | I | None | **PASS** | `2b492dde-41d3-469e-a4a7-a31704466d6f` |
| 30R | Conditional Education grounding versus a separately routed Investment answer | B | B → tool:education_retriever:c6c21d44b105aef8 (education_context) | **FAIL** | `1137f6f3-9ab2-45c3-b5c4-7c9cc71977a5` |

## Failures

Across all 42 turns: 2 withheld answers; 3 delivered incomplete answers. Graph failures: none.

- **Case 9** — After localized correction and a fresh safety review, Spending was retained but the requested zero-based budgeting explanation was removed. The delivered answer has an empty heading and is marked incomplete.
- **Case 16** — The delivered answer is marked incomplete. Savings allocation and diversification are present, but the review found missing spending-informed Budget coverage and repair was skipped for the forecast deadline.
- **Case 16P** — The safety review withheld the entire answer; no requested guidance was delivered.
  Safety review withheld the answer. Recorded review and validation codes are retained in the evidence.
- **Case 17** — The safety review withheld the entire answer; no requested guidance was delivered.
  Safety review withheld the answer. Recorded review and validation codes are retained in the evidence.
- **Case 30R** — After localized correction and a fresh safety review, the confirmed savings allocation was retained but the requested general liquidity explanation was missing. The delivered answer is marked incomplete.

## Trace observations

- All five failed turns recorded the user request as allowed, including the two withheld answers. The refusal concerned generated content, not prohibited user intent.
- Cases 9 and 30R passed safety review after localized correction, but the new review marked requested coverage incomplete. Case 9 lost its budgeting explanation; 30R retained an ETF-specific limitation rather than the requested general liquidity explanation.
- Case 16 had incomplete Budget coverage. Financial repair was skipped with `REPAIR_DEADLINE_EXCEEDED`: estimated repair duration 43.5 seconds, remaining duration 32.7 seconds.
- Case 16P remained blocked after correction and a separately reviewed reduced answer. Case 17 was blocked for generated `personal_advice` and `factual_qualification`; correction was marked unavailable with `REVIEW_CATEGORY_NOT_CORRECTABLE`.
- All 63 available numeric assertions passed. Four assertions could not be checked because blocked exports withhold specialist data. There were no numeric mismatches.

## Consistency check

| Case | First run | Repeat | Same outcome |
| --- | --- | --- | --- |
| 5 | pass | pass | True |
| 9 | fail | pass | False |
| 13 | pass | pass | True |
| 21 | pass | pass | True |
| 25 | pass | pass | True |
| 29 | pass | pass | True |
| 30 | pass | fail | False |

## Deployment identity

- 42 trace(s): build `7356713e1979331678c86a4f446d70ae9bfb4b76`, prompt set `v10`, hash `28ba6a7b66460d3766c976a63f33d9439665f8ebff9aa635dd399f1540fea1dc`.

Build identity is reported by the saved AI traces. AWS deployment state was not independently queried. The repository at test start was `7356713e1979331678c86a4f446d70ae9bfb4b76`.

Two samples for seven selected cases can expose inconsistencies, but do not establish a general model reliability rate. Browser-control delays are recorded separately from application outcomes.
