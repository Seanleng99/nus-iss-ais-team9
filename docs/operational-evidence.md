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
| Formal Bedrock model comparison | Both profiles passed 45/45 structural runs; candidate awaits blinded human review | [GitHub Actions run 33177819211](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33177819211) |
| Education RAG source governance | Passed manifest, S3 object, checksum, metadata, freshness, Knowledge Base, data source, and ingestion-state audit; evidence retained for 90 days | [GitHub Actions run 33193755856](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33193755856) |

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

## Candidate Model Decision

The formal 2026-08-28 AWS comparison ran 15 cases three times per model through the service orchestrator and prompt set v3. Both the Nova Lite and Nova Micro APAC profiles were active from Singapore, listed six APAC destinations, completed all 45 cases, and had zero execution errors.

Nova Lite passed 45/45 structural runs with 7.69-second P95 and USD 0.012306 estimated cost. Nova Micro also passed 45/45, with 7.08-second P95 and USD 0.005437 estimated cost. The versioned policy therefore recorded `pending_human_review`. The blinded 45-row review remains required, and `apac.amazon.nova-lite-v1:0` stays selected in the meantime; see `docs/model-selection.md`.

## Education RAG Source Governance

On 2026-08-28, the six-document Education corpus was placed under manifest version `investment-education-sg@2026-08-28.1`. The controlled metadata migration verified every deployed document checksum before changing its sidecar. Bedrock ingestion job `D4C4MMUERE` completed with six documents scanned, six metadata documents modified, and zero failures.

The post-ingestion AWS audit passed with zero issues: knowledge base `X2BXBRYX2X` was active, data source `H6D6Z2RUL2` was available, all 12 expected S3 objects were present, no unmanifested object existed under the approved prefix, and all retrieved chunks carried the pinned corpus version, document checksum, document version, and review deadline. The first retained workflow audit passed at commit `4286ac76f44af2317aea2ace6041cea1cba231ab`; its artifact expires on 2026-11-26. The earliest source review is due 2026-11-14. The versioned evidence and operating procedure are in `docs/rag-source-governance.md`; the weekly workflow retains subsequent audits for 90 days.

## Open Evidence

- Human SNS or incident-channel subscription confirmation and tested delivery.
- Representative-user validation of explanations and confidence presentation.
- Complete and approve the current blinded Nova Micro review before any model change.
- Review the exact-version base-image CVE exceptions before they expire on 2026-09-18.
