# Operational Evidence Register

This register contains privacy-safe evidence for the synthetic-data AWS demo. It does not approve real personal financial data or production users.

## Verified Baseline

- Baseline date: 2026-08-24
- Commit: `96642b1707e5be1c7e28f0ec8fe5b34e8432f818`
- Model/profile: `apac.amazon.nova-lite-v1:0`
- Prompt set: `v3`

| Evidence | Result | Reference |
|---|---|---|
| CI and LLMSecOps | Passed backend/AI tests, migrations, SAST, integration/load smoke, and hardened image builds | [GitHub Actions run 32714632489](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/32714632489) |
| AWS release | Passed immutable image scanning, migration task, ECS deployment, and health/AI-safety smoke tests | [GitHub Actions run 32714790085](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/32714790085) |
| AWS operational validation | Passed service, autoscaling, dashboard, alarm, trace-retention, repeated live-model, RAG, load, and cleanup gates | [GitHub Actions run 32715294232](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/32715294232) |

The operational artifact recorded 15 of 15 live cases passed, 100 percent dependency/RAG/routing/safety category rates, 7.32-second live P95, 41,438 audited tokens, and USD 0.004134 estimated model cost. The bounded load artifact recorded 10 of 10 successes at concurrency two, 4.85-second P95, and zero chat-session cleanup failures. The manual replacement exercise had already passed in the preceding operational run.

GitHub retains the operational artifact for 90 days. Copy the final approved artifact and workflow summaries into the assessment evidence store before that retention period expires.

## Threshold Decision

Using the baseline above, evaluation policy v4 sets these default operational gates:

- live cases repeated three times;
- 100 percent structural case pass rate;
- live coaching P95 no greater than 10 seconds;
- load P95 no greater than 8 seconds;
- 100 percent bounded-load success and zero cleanup failures; and
- estimated live-evaluation cost no greater than USD 0.05 per workflow run.

The expanded live suite must produce a new successful artifact before it replaces this baseline.

## Open Evidence

- Human SNS or incident-channel subscription confirmation and tested delivery.
- Expanded policy-v4 live-model artifact after deployment.
- Human-reviewed explanation, confidence, and fairness results.
- Candidate-model quality, safety, latency, cost, entitlement, and inference-geography comparison.
- Approved Education Knowledge Base ingestion and source-freshness record.
