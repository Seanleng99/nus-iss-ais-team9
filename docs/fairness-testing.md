# Fairness controls and evaluation

The initial fairness increment adds a shared runtime policy, a typed Compliance
finding, independent correctness checks for paired cases, and an end-to-end
reporting harness. It reduces specific risks; it does not establish that the
application or foundation model is free of bias.

## Fairness contract

For equivalent financial facts, irrelevant demographic cues must not change
calculations, access to useful help, or safety decisions. Names, ethnicity,
nationality, religion, gender, age, disability and dialect must not be used to
invent financial capability, literacy, spending habits or risk tolerance.

Presentation may legitimately change to honor language or accessibility
preferences. Explicit financial needs, such as a medical expense or a different
planning horizon, may legitimately change an answer. A demographic disclosure,
discussion of cultural needs, or rejection of a stereotype is not itself unsafe.

## Runtime enforcement

`apps/ai-service/app/core/prompts.py` appends the fairness policy to every catalog
prompt, including routing, specialists, synthesis, composition and Compliance.
The effective prompt-content hash includes the shared policy. The existing v10
manifest remains the catalog release identity; the new content hash identifies
the amended instructions and invalidates repair authority captured under old
instructions. This local change has not established deployed acceptance.

Compliance has a `demographic_assumption` category. A defective draft is withheld.
For an otherwise allowed request, removal is eligible only when a validated
issue identifies an owned section and locates the offending claim. Unsupported
demographic assumptions cannot authorize changing financial inputs. Existing
correction limits, grounding checks and a fresh independent full review still
apply. A failed correction or a mixed unsafe category remains withheld. Fixed
English and Chinese explanations expose the reason without displaying rejected
prose. This is a model-assisted semantic check, not a comprehensive deterministic
bias detector; generation and review can share model blind spots.

Stored fairness demographics remain consent-based and separate from coaching.
The backend regression additionally changes the demographic record and verifies
that the full normal coaching snapshot is unchanged.

## Offline paired cases

`apps/ai-service/app/evals/datasets/fairness_consistency.jsonl` contains 19 authored
synthetic pairs across Budget, Spending, Goal arithmetic, Investment Education,
missing-income clarification and prohibited product-selection requests. Dimensions
include names, English/Chinese, writing style, Singlish, age, gender, ethnicity,
nationality, religion, disability and combined attributes. Financial context and
the intended task remain fixed within each pair.

Every pair has an independent expected outcome. Both answers must meet those
expectations **and** match the specified structured fields. Identical wrong
routes, refusals or calculations fail. The Budget baseline uses confirmed monthly
recurrence and authored numerical expectations rather than matching two null
calculations. Goal cases explicitly request contribution arithmetic rather than
conflating it with personal funding feasibility.

English/Chinese Education cases require the core ETF source and grounded evidence
independently. Supplementary source IDs may differ across translations; exact
source-list equality is not a semantic quality measure. The Chinese side also
has an independent response-language check. Human review must still assess
equivalent topic coverage and explanation quality.

Evaluation policy v9 retains a 100% correctness-and-consistency requirement and
zero regression for this suite. These offline checks use fixture model responses.
Scripted review tests prove enforcement of valid and invalid reviewer verdicts;
they do not measure whether a live model recognizes every demographic assumption.

## End-to-end report

Run from the repository root with an authorized synthetic environment and its
service key in `BACKEND_API_KEY`:

```powershell
.venv/Scripts/python.exe -m infra.scripts.fairness_live_evaluation `
  --url https://YOUR-TEST-HOST/api/coach `
  --expected-model-id gpt-6-luna `
  --commit-sha YOUR-VERIFIED-40-CHARACTER-DEPLOYED-COMMIT `
  --repeats 3 `
  --input-cost-per-million YOUR-CHECKED-INPUT-RATE `
  --output-cost-per-million YOUR-CHECKED-OUTPUT-RATE `
  --maximum-estimated-cost-usd 0.50 `
  --maximum-total-tokens 1000000 `
  --output artifacts/fairness-live.json `
  --review-output artifacts/fairness-human-review.csv
```

The harness uses the existing owned synthetic-fixture APIs, independently seeds
each side, executes both sides repeatedly, and cleans up sessions and workspaces.
Its report includes per-dimension counts, failed checks, answers and traces,
model/prompt/build identity, observed corpus versions, latency, token usage and
estimated cost. The service key is never stored in the report or passed on the
command line. Synthetic classification is an author assertion; datasets must be
reviewed before use and must never contain real identifiers or financial records.

Incomplete pairs, wrong independent outcomes, changed identities, mismatched
corpus versions, failed cleanup, and unknown live usage fail objective acceptance.
Cost and token thresholds stop new requests; one in-flight request may exceed a
threshold, and the final report must also remain within both limits. Input and
output rates are explicit test assumptions, not authoritative provider billing.
Fixture-mode runs do not invoke a paid model and do not enforce model-token budgets.

The CSV hides model identity and automated verdicts, randomizes answer order, and
leaves reviewer scores blank. Review correctness, helpfulness, respect, uncertainty
and unsupported assumptions. Use reviewers competent in each answer's language;
resolve disagreements and record pair-level differences. An objective pass never
sets human acceptance: `human_review_status` remains `pending` and
`fairness_acceptance` remains `not_established`.

## Remaining evidence gaps

The initial set covers single-turn synthetic requests, with sparse examples per
dimension. Repeated generations share scenarios and are not independent population
samples. Per-dimension rates describe the authored cases, not demographic-group
service rates. Independent human review, representative-user validation,
multi-turn demographic leakage, expanded coverage and calibrated uncertainty
remain outstanding. Real-data cohort monitoring needs explicit purpose and
consent controls; protected attributes must never be inferred for monitoring.

The risk and accountable follow-up remain recorded as AI-19 in the
[security risk register](security-risk-register.md).
