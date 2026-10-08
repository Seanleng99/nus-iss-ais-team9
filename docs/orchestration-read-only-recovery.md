# Recovery after the third 8 October live retest

The [retest after dae539d](agent-reasoning-live-test-results-2026-10-08-postdae539d.md)
passed 27 of the 34 original turns. Cases 13, 19P, 21, 22, 25, 26b and 29 failed;
additional full-chain case 35 also failed. These changes address the routing,
grounding and recovery gaps exposed by that run. Historical outcomes remain unchanged;
the source changes have not yet been verified against a deployed model.

## Why a previous pass can become a failure

The preceding run passed 29 of 34 turns. Cases 5, 17, 19 and 20 improved in the
latest run, while six other turns regressed; case 25 remained incomplete. The saved
financial records were unchanged between the two exports. Audit metadata reports
different build commits and different prompt content hashes, although both use the
single current v9 contract and OpenAI / gpt-6-luna:

| Run | Trace-reported build | Prompt content hash |
| --- | --- | --- |
| Previous | `02877400aeca9df3936b44089f5f5aee37c767cf` | `96cbcd7137ab2dc47193c4155d0a330e286cf10c67bbe75ff00312eeaa6b3604` |
| Latest | `dae539d22250b33a4f93cf611e2bf5be8cf7e981` | `89472ed166e362fe92135f57540c8d1f077af1d4a3bc62694b03950923445f89` |

These are identities carried by the application traces, rather than an independent
AWS deployment inspection. A changed build can change both generated prose and
review decisions. Semantic model calls can also vary for the same input. The OpenAI
gateway does not send its configured temperature to the provider, so the failures
cannot be attributed to that setting. Each run used one attempt per turn; the
observations establish regressions, not a measured failure probability or a proved
causal effect of a particular prompt edit.

Several latest failures reached the correct specialist graph and then received a
review veto. A correct graph alone does not establish acceptable reasoning. A
reviewer may identify a qualification defect, while an overly strict recovery
predicate makes a correctable draft appear permanently unrepairable. The safe
export cannot reveal the rejected claim or every predicate behind historical
denials. This change records those predicates without publishing rejected prose.

## Changes and their boundaries

| Observed gap | Implemented correction | Regression coverage |
| --- | --- | --- |
| Owned qualifications in 13, 19P, 22 and 26b were denied recovery despite remaining resources | Separate an unsafe original draft from an allowed correction; record failed eligibility predicates | False or omitted original safety flag, prohibited categories, targeted Education edits, rejected unrelated edits |
| Forecast case 21 returned a capture handoff without normal writer/reviewer grounding | Ground the read-only forecast, clear the resolved capture state, and use normal independent review and bounded correction | Forecast versus payment, immutable grounding, conflicting legacy capture flag, identity and currency scope |
| Goal case 25 omitted reserve context and stayed on saved-goal arithmetic | Classify Goal mode before writing; acquire the existing authorized expense aggregate and Education context for reserve reasoning | Omitted router education topic, reserve paraphrase, coverage qualification and no new financial edge |
| Composition-owned Investment case 29 had no financial authority or previous synthesizer usage | Recognize sealed Education authority and forecast the first planned synthesis call | Metered first synthesis, unknown usage denial and failed second review |
| Reconciliation case 35 entered Budget capture/planning and omitted Spending consumption | Use a semantic read-only reconciliation operation and validate its required capability consumption | Paraphrases, capture/planning conflicts, bounded dependency-plan correction and the full provider chain |

### Semantic operations and conditional dependencies

The router may assign a typed `operation`: `analysis`, `reconciliation`, `forecast`,
`record_read`, `planning` or `record_change`. The server checks which operations
belong to each specialist. The model chooses the intent; the server validates its
structural consequences. Runtime code contains no test IDs, expected answers or
new prompt-phrase exceptions.

For Budget, `analysis` and `reconciliation` clear legacy capture/planning flags.
Reconciliation means comparing recorded category totals against existing limits;
it neither proposes new limits nor enters the saved-record command workflow.
Budget offers the existing authorized `transaction_category_totals` capability
as required for that operation. A dependency plan declaring readiness without
consuming it fails contract validation and gets the existing bounded correction.
A contradictory `requires_spending=false` assignment also fails validation.

For ordinary capacity or conceptual tasks, an offered Spending capability remains
optional. A saved confirmed allocation can supply capacity without recorded
spending. Co-selection alone still creates no edge, and independent ready tasks
can execute concurrently. The supported full chain remains Goal consuming Budget
capacity, with Budget consuming Spending totals when its own work requires them.
The direct Goal–Spending edge remains deferred.

Production routing no longer forces Budget capture/planning from the old explicit
selection regex. Offline fixtures retain their local recognizers, including the
existing localized budget-command recognizer. They do not control production
semantic decisions or establish deployed routing accuracy.

### Reserve context before the Goal writer

Goal assignments may provide `goal_mode=standard` or `emergency_reserve`. An explicit
reserve assignment must also carry its canonical Education topic. When the mode
is omitted, the scoped Goal input classifier resolves it once from the owned
question and resolved follow-up, even if a capacity requirement was already supplied.
The private cached result is retained across task resumes.

Reserve mode acquires the existing server expense aggregate before grounding and
offers the governed Education context dependency. The aggregate retains its
logged-record and incomplete-coverage qualifications; it does not become a complete
household expense figure or a new Spending-agent capability. A reserve benchmark
is distinct from arithmetic on the saved goal balances. The fix supplies this
context before the first writer call; it does not add an unbudgeted post-review
retrieval/replanning loop. A semantically misclassified explicit mode remains a
model-quality limitation requiring live evaluation.

### Read-only forecast evidence

The existing Spending extractor still resolves forecast dates and filters. A typed
forecast operation selects that extractor even when its legacy capture flag
conflicts. After extraction returns a forecast, Spending clears capture state and
grounds a normal narrative. That narrative can receive the same one-round
qualification correction as other read-only financial reasoning.

`ledger_forecast` projects only explicitly supplied ledger recurrence terms, using
the shared recurrence calendar. It groups by obligation identity and chooses the
latest record; conflicting latest terms and missing cadence remain unknown. It
does not infer schedules from merchant names, count several payments as separate
obligations, convert currencies, or treat scheduled amounts as paid expenses.
Recorded payments and their scope are separate evidence. Normal Spending analysis
does not receive extra recurrence inputs merely because this workflow exists.

This AI grounding is a qualified ledger projection, not the complete household
forecast. The unchanged `spending_draft` handoff lets the backend separately verify
workspace bills, current schedules and settlements for its authoritative forecast.
The AI tool cannot independently establish those backend facts. Forecast results
also cannot provide the Spending capability for recorded category totals.

### Answerability, original safety and repairability

`complete` describes whether the requested answer is covered. `blocked` and
`financial_language_safe` describe the original draft's acceptability.
`request_allowed` describes the user's request. None of these is a model-issued
permission to repair. The server derives repairability from all owned issues,
their categories, locations, evidence and the request boundary.

A false or omitted original safety flag no longer automatically forbids correcting
an owned factual qualification or citation/attribution defect. An unsupported claim
still requires an owned location and either removal or an existing supporting
evidence reference. Personal advice, return guarantees, privacy and injection
categories remain ineligible; unsafe reviewer instructions cannot be passed to a
writer. Rejected text remains untrusted, and no correction makes the original
draft releasable.

Financial and Education snapshots both establish server-owned review authority.
Education authority includes the retrieved evidence, scope, semantic coverage and
permitted model-knowledge fallback. Composition correction can therefore use a
sealed Education-only answer, including supported stable concepts with explicit
limitations on current or personal facts. There is no new retrieval permission.

Located specialist defects receive offsets translated into their original rendered
summary. Financial text and Education text outside those locations must remain
unchanged. Education validation includes application-supplied source labels and
ordered options. A generated unrelated edit fails the bounded structured-output
correction. Completion issues without a located claim retain the existing owned
completion path; removing a claim never establishes a missing input. Every
successful correction must pass a second full independent review. A failed or
unavailable correction retains the original veto.

### Resource forecasts and safe diagnostics

An Investment-only answer can normally bypass synthesis. If independent review
then attributes a defect to composition, there is no prior synthesizer call to
estimate from. Recovery now builds the actual planned synthesis payload without
calling the model or emitting a fictitious `synthesis.started` event. Admission
uses its conservative byte-size input estimate, full output limit and contingency.
The estimate is labeled `planned_prompt_byte_bound`; it is not provider usage.

Actual preceding calls must still have valid measured usage. The gateway checks
the new call's real usage. The existing call budget, token ceiling, task attempts,
workflow deadline and single semantic correction round remain in force.

Safe routing metadata retains validated operation and Goal mode codes. Review
events retain request/safety flags and `repair_blockers`, including missing owned
issues, forbidden categories, unlocated claims, unsafe review output and filtered
correction instructions. Resource admission records its separate blockers. Trace
storage and viewer sanitization retain these codes while excluding questions,
claim quotes, requirements, personal values and rejected prose.

## Verification and rollout

The new `test_reasoning_recovery_contracts.py` suite exercises 21 cases, including
negative safety/resource tests and malformed semantic contracts. It uses controlled
gateway responses to verify application behavior; it does not prove model agreement
with those responses. Historical tests were updated where they depended on the
removed production regex or treated every unsafe original draft as uncorrectable.
Checks for prohibited requests, unsafe categories and failed corrections remain.

Local verification on 8 October 2026:

| Check | Result |
| --- | --- |
| Complete AI-service suite | 1,869 passed; one Windows symlink-permission skip |
| Final affected suites, including the new recovery tests | 134 passed |
| New recovery cases | 21 passed |
| Shared contracts and CI agent-test selection | 78 passed |
| Backend trace persistence and review reasons | 20 passed |
| Decision trace viewer | 15 passed |
| LLMSecOps fixture gate | 87 cases across eight datasets passed |
| Authored passage retrieval and scope benchmark | 100 cases passed; generated answer quality not measured |
| Ruff, Chinese source-code scan and diff whitespace | Passed |

The final affected suites ran after the complete suite to verify the last narrow
forecast filter-name and Education render-validation adjustments. FastAPI and
Streamlit tests required execution outside the Windows sandbox because of local
socket and temporary-directory restrictions. The full suite retained an existing
fixture serializer warning; no application failure remained. See the
[content-free verification evidence](evaluation-evidence/orchestration-read-only-recovery-2026-10-08.json).

Changes use the single packaged `prompts/current` contract. Its content hash changes;
there is no runtime historical-version selector. Commit, deployment and repeated
signed-in browser testing remain separate steps. Live validation should repeat
the original prompts and paraphrases against one build, prompt hash and financial
snapshot, reporting per-turn recovery reasons as well as graph and answer checks.
