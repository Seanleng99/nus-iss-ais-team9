# Operational Evidence Register

This register contains privacy-safe evidence for the synthetic-data AWS demo. It does not approve real personal financial data or production users.

## Verified Baseline

- Baseline date: 2026-08-28
- Commit: `a1cb89353da855f5253dbdbbee2c396414053aac`
- Model/profile: `apac.amazon.nova-lite-v1:0`
- Prompt set: `v3`

| Evidence | Result | Reference |
|---|---|---|
| CI and LLMSecOps | Passed backend/AI tests, migrations, SAST, policy-v4 evaluation, integration/load smoke, and hardened image builds | [GitHub Actions run 33140409703](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33140409703) |
| AWS release | Passed immutable image scanning, migration task, all three ECS deployments, and health/AI-safety smoke tests | [GitHub Actions run 33140505433](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33140505433) |
| AWS operational validation | Passed service, autoscaling, dashboard, alarm, trace-retention, expanded repeated live-model, RAG, load, and cleanup gates | [GitHub Actions run 33164881856](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33164881856) |

The operational artifact recorded 33 of 33 live runs passed across 11 cases repeated three times, 100 percent dependency/RAG/routing/safety category rates, 6.41-second live P95, 102,681 audited tokens, and USD 0.010126 estimated model cost. The bounded load artifact recorded 10 of 10 successes at concurrency two, 4.34-second P95, and zero chat-session cleanup failures. Task replacement was not re-exercised in this run; the successful replacement evidence from [run 32715294232](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/32715294232) remains applicable.

GitHub retains the operational artifact for 90 days. Copy the final approved artifact and workflow summaries into the assessment evidence store before that retention period expires.

## Threshold Decision

Using the baseline above, evaluation policy v4 sets these operational gates:

- live cases repeated three times;
- 100 percent structural case pass rate;
- live coaching P95 no greater than 10 seconds;
- load P95 no greater than 8 seconds;
- 100 percent bounded-load success and zero cleanup failures; and
- estimated live-evaluation cost no greater than USD 0.05 per workflow run.

The GitHub environment variables enforce the 10-second live P95, 8-second load P95, and USD 0.05 cost limits. They replaced the original 30-second and USD 1.00 characterization values before run 33164881856.

## Open Evidence

- Human SNS or incident-channel subscription confirmation and tested delivery.
- Human-reviewed explanation, confidence, and fairness results.
- Candidate-model quality, safety, latency, cost, entitlement, and inference-geography comparison.
- Approved Education Knowledge Base ingestion and source-freshness record.
- Review the exact-version base-image CVE exceptions before they expire on 2026-09-18.
