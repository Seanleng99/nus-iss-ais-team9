> **Superseded snapshot:** The retest is now complete. See the [final report](agent-reasoning-live-test-results-2026-10-08-post0287740.md) for all 34 original turns and additional case 35. The partial observations below are retained unchanged.

# Partial live retest after 0287740 — 8 October 2026

**The suite is incomplete: 20 of the original 34 turns completed. Nineteen returned substantive answers; case 17 was withheld. Case 5 has a response consistency issue. Dependency and parallel execution verification remain pending for all cases.**

The completed turns ran through the signed-in **Edge browser plugin** from **13:17–13:37 SGT** against **Agent Reasoning Demo — Synthetic**, with October 2026 selected. Every completed turn used a fresh chat. The UI reported prompt set **v9**. That label does not establish the deployed Git SHA.

This report records one attempt per prompt and preserves the original 34 approved prompts. Case 35 is an additional explicit full-chain demonstration and has **not** run. The historical reports are unchanged.

## Observed answer outcomes

| Case | Scenario | Answer outcome | Reference ID |
|---|---|---|---|
| 1 | Spending: single specialist | Substantive answer | `1c437fdb-6209-4b7a-8344-fd1befda282f` |
| 2 | Budget: single specialist | Substantive answer | `0dea5048-e64c-4dea-954c-7cdce44b4a06` |
| 3 | Goal: single specialist | Substantive answer | `bc0db570-cf71-44ba-bd5e-cdcc385675b0` |
| 4 | Investment: single specialist | Substantive answer | `7e557246-433d-4a15-810e-17db51be0a88` |
| 5 | Budget + Spending: dependency | Substantive answer; consistency issue | `02d834b5-c1c8-4b23-a68a-aaeed1276d0f` |
| 6 | Budget + Goal: dependency | Substantive answer | `2a09fc13-3254-4c41-8f83-bf5ce7e88d1c` |
| 7 | Budget + Spending + Goal: dependency | Substantive answer | `b86813c8-12a2-408f-97e6-a1c96d75065c` |
| 8 | Spending + Goal: dependency requested, exact pair unsupported | Substantive answer | `575a360e-a7cd-4f86-abd0-20f4fd726581` |
| 9 | Budget + Spending: independent parallel candidates | Substantive answer | `153b1261-8318-49df-9e65-f7ef2c704bcf` |
| 10 | Budget + Goal: independent parallel candidates | Substantive answer | `68bc44b0-a6b7-4e3b-81e0-6388f36790e4` |
| 11 | Budget + Spending + Goal: independent parallel candidates | Substantive answer | `0aa26176-d453-4f22-9a8b-f90815fcd3d0` |
| 12 | Spending + Goal: independent parallel candidates | Substantive answer | `34aa92f8-363b-482a-aec2-1cfc1eae893c` |
| 13 | Spending + Investment | Substantive answer | `e142cfe3-268c-4e8a-a7f5-0af6c4590416` |
| 14 | Budget + Investment | Substantive answer | `203ff5d7-bdc9-4597-b343-081a52601740` |
| 15 | Goal + Investment | Substantive answer | `1eb95600-e71b-456b-b4dd-93b3978e29a7` |
| 16 | Budget + Spending + Investment | Substantive answer | `86a190c5-b8e4-4ac0-8b6d-4059de517a5b` |
| 16P | Independent Investment combination | Substantive answer | `1ea581d7-4af1-4c63-b099-6519705b45f6` |
| 17 | Spending + Goal + Investment | Withheld | `789d6b4f-a548-489c-9b65-7bb41a724cfa` |
| 18 | Budget + Goal + Investment | Substantive answer | `4e758b22-1a12-42bf-a9b6-8bbe8dc213c4` |
| 18P | Independent Investment combination | Substantive answer | `e3b333e6-d9a0-4660-82c2-215afdd42cc1` |

The previously withheld cases **3, 5, 13 and 15** now return answers. Case 17 is a newly observed withheld answer. The emergency-fund case 25 has not been reached.

In case 5, Budget correctly uses the saved limits and identifies Food SGD 10, Entertainment SGD 25 and Shopping SGD 20 over their limits. The Spending paragraph then says “there are no budget limits here.” This clashes with the combined response; it must not be counted as a fully clean response merely because review allowed it.

Case 17 displays the generic verification refusal and the UI states that safety review blocked the response. Its cause cannot yet be narrowed to a particular reviewer issue or repair decision from the available UI evidence.

## Interruption and remaining checks

The plugin JavaScript call timed out during case 19 and reset its kernel. Its runtime then failed to import with a filesystem permission error. An explicitly approved copy of the installed runtime into ignored test artifacts also failed to import. No alternative native browser control or direct application API was used.

Case **19 was submitted**, but its result has not been recovered; do not resubmit it without checking the existing conversation first. Remaining original turns: **19, 19P, 20, 21, 22, 23, 24, 25, 26a, 26b, 27, 28, 29, 30**. Case **26b** must continue **26a**.

Current trace export, unique prompt/time correlation, task dependency edges, provider reuse, actual specialist execution overlaps and all four decision-viewer tabs remain unverified. A baseline profile export is stored only under ignored artifacts; a final export is still needed to establish that all financial records are unchanged.

A local bookkeeping error replaced case 2’s DOM with case 3’s DOM before it was corrected. Case 2’s reference is preserved from the observed tool output, and case 3’s answer DOM is preserved with a broad matching window. These must be reconciled with exported user timestamps before producing the final full-suite report.

The [sanitized partial evidence](evaluation-evidence/agent-reasoning-live-v9-2026-10-08-post0287740-partial.json) contains the completed prompts, answer DOM excerpts and reference IDs. Raw exports and full DOM captures, which include account metadata, remain in ignored artifacts.
