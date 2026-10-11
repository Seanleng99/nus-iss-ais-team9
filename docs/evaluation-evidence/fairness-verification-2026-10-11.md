# Fairness increment verification — 11 October 2026

The fairness changes are implemented in the local working tree. They have not
been deployed. The v10 catalog's effective prompt-content hash now includes the
shared fairness policy; evaluation policy is v9.

| Verification | Result and meaning |
|---|---|
| Focused AI regressions | 252 passed across fairness controls, effective prompt identity, evaluation scoring, scoped review, financial repair, safety and Chinese explanations |
| Harness and shared/config regressions | Initial 199 passed; final focused run 116 passed after stricter dataset validation; these overlap and must not be added as distinct coverage |
| Backend demographic-isolation regression | Passed: consent is required, changing demographics leaves the full coaching snapshot unchanged, and withdrawal removes the record |
| Full offline evaluation policy | 136/136 cases/pairs passed across nine suites, including 19 fairness pairs; fixture-model evidence |
| Isolated backend-to-AI fixture evaluation | 38/38 pair executions passed (19 pairs, two repeats), across 76 requests; all synthetic workspaces and sessions were cleaned up |
| Current-model evaluation | Blocked before obtaining model answers. The first request failed input-token preflight; a separate token-count-only diagnostic received HTTP 401 / `OPENAI_AUTHENTICATION_FAILED` |
| Human fairness review | Pending; fixture answers do not establish current-model explanation quality |

The [completed fixture report](fairness-local_fixture-2026-10-11-e3047345.json)
retains paired questions, answers, independent correctness, structured projections,
per-dimension counts, prompt/build identity, corpus versions, traces and cleanup.
It used an isolated local SQLite backend, a fixture model and fixture retrieval.
The emitted build commit is the checkout's HEAD; uncommitted changes are explicitly
declared and their diff digest recorded. This is not deployed-build verification.
Fixture token entries are not actual paid-provider usage.

The [fixture human-review worksheet](fairness-fixture-human-review-2026-10-11.csv)
demonstrates the randomized, model-blind review format. Scores are blank. The
[blocked current-model report](fairness-openai-2026-10-11-c741fef7.json)
retains the failed execution and cleanup evidence. Its zero completed pairs and
planned-pair zero pass rates represent missing evidence, not observed bias.
Usage remains marked unknown by the fail-closed live harness; a zero estimate
must not be interpreted as verified provider billing.

Two earlier fixture attempts stopped because paid-model usage accounting was
inappropriately applied to fixture calls and because the isolated reservation
quota was insufficient for all fixture requests. Their evidence remains in
`artifacts/fairness-local_fixture-2026-10-11.json` and
`artifacts/fairness-local_fixture-2026-10-11-91fb3b8e.json`. Fixture mode now avoids
paid-provider budgets, and only the disposable local test environment's hourly
reservation quota was raised. Production quotas were not changed.

Live model acceptance requires a valid configured credential, a complete repeated
run, and independent bilingual human review. The suite's sparse single-turn
synthetic pairs do not establish representative-user or multi-turn fairness.
See [fairness testing](../fairness-testing.md) for the implementation contract and
remaining evidence gaps.
