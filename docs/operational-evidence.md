# Operational Evidence Register

This register contains privacy-safe evidence for the synthetic-data AWS demo. It does not approve real personal financial data or production users.

## Verified Baseline

- Baseline date: 2026-08-31
- Commit: `2cc386ec4ac724876fa92e226237a969a2ce8db7`
- Model/profile: `apac.amazon.nova-lite-v1:0`
- Prompt set: `v4`

| Evidence | Result | Reference |
|---|---|---|
| CI and LLMSecOps | Passed 159 AI-service tests, two subtests, all 52 policy-v6 evaluation cases/pairs, migrations, SAST, integration/load smoke, and hardened image builds | [GitHub Actions run 33347157673](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33347157673) |
| AWS release | Passed immutable image scanning, migration task, all three ECS deployments, and health/AI-safety smoke tests; AI revision 36 and backend revision 67 reached steady state | [GitHub Actions run 33347260233](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33347260233) |
| AWS operational validation | Passed service, autoscaling, dashboard, alarm and confirmed-subscription, edge-security, trace-retention, repeated live-model/RAG, bounded-load, and cleanup gates | [GitHub Actions run 33349636155](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33349636155) |
| Formal Bedrock model comparison | Nova Lite passed 45/45; Nova Micro passed 42/45 and was rejected at the dependency gate; baseline retained | [GitHub Actions run 33354207859](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33354207859) |
| Education RAG source governance | Passed manifest, S3 object, checksum, metadata, freshness, Knowledge Base, data source, and ingestion-state audit; evidence retained for 90 days | [GitHub Actions run 33193755856](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33193755856) |
| Policy RAG CI and AWS release | Passed Policy retrieval/evaluation controls, immutable-image scanning, deployment, and live provenance/persisted-trace smoke checks | [CI run 33229618646](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33229618646) and [release run 33229698149](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33229698149) |
| Policy RAG source governance | Passed manifest, S3 object, checksum, metadata, freshness, Knowledge Base, data source, and ingestion-state audit with three approved sources and zero issues; evidence retained for 90 days | [GitHub Actions run 33231041612](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33231041612) |
| Custom-domain and HTTPS edge activation | Passed custom viewer hostname, TLS 1.2 policy, HTTPS-only TLS 1.2+ ALB origin, origin-header enforcement, and direct-origin denial | [GitHub Actions run 33280566917](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33280566917) |

The post-change operational artifact recorded 39 of 39 live runs passed across 13 cases repeated three times, 100 percent dependency/RAG/routing/safety category rates, 8.68-second live P95, 260,859 audited tokens, and USD 0.021336 estimated model cost. The bounded load artifact recorded 10 of 10 successes at concurrency two, 6.35-second P95, and zero chat-session cleanup failures. The workflow also recorded one confirmed email subscription, valid custom-domain TLS, denied direct-origin access, and a successful trace-retention task. Task replacement was intentionally not re-exercised in this run; the successful replacement evidence from [run 32715294232](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/32715294232) remains applicable.

The first post-change attempt, [run 33346011494](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33346011494), passed its infrastructure, notification, edge, retention, and load checks but failed the live-evaluation gate at 32 of 39 runs. Seven HTTP 503 responses mapped to exhausted model-gateway retries while Budget and Goal agents stochastically replanned Education dependencies that deterministic topic rules had already established. Commit `2cc386ec4ac724876fa92e226237a969a2ce8db7` made those allowlisted Education requests deterministic, removed the redundant planner calls, and added privacy-safe HTTP status and correlation diagnostics. CI, release, and run 33349636155 then passed without a live failure.

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

The formal 2026-08-31 AWS comparison ran 15 cases three times per model through the service orchestrator and prompt set v4. Both the Nova Lite and Nova Micro APAC profiles were active from Singapore, listed six APAC destinations, completed all 45 executions, and had zero invocation errors.

Nova Lite passed 45/45 structural runs with 7.54-second P95 and USD 0.014744 estimated cost. Nova Micro passed 42/45, with 8.02-second P95 and USD 0.006486 estimated cost. Micro failed all three repeats of the missing-income dependency case by marking the request blocked while correctly identifying that the Budget agent needed user input. Its overall pass rate was 93.33 percent and its dependency pass rate was 66.67 percent against 100-percent gates. The versioned policy therefore recorded `retain_baseline` and `human_review_required: false`; `apac.amazon.nova-lite-v1:0` remains selected. The JSON report, 45-row blinded diagnostic file, and separate review key are retained for 90 days in [run 33354207859](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33354207859). See `docs/model-selection.md` for the complete decision record.

## Education RAG Source Governance

On 2026-08-28, the six-document Education corpus was placed under manifest version `investment-education-sg@2026-08-28.1`. The controlled metadata migration verified every deployed document checksum before changing its sidecar. Bedrock ingestion job `D4C4MMUERE` completed with six documents scanned, six metadata documents modified, and zero failures.

The post-ingestion AWS audit passed with zero issues: knowledge base `X2BXBRYX2X` was active, data source `H6D6Z2RUL2` was available, all 12 expected S3 objects were present, no unmanifested object existed under the approved prefix, and all retrieved chunks carried the pinned corpus version, document checksum, document version, and review deadline. The first retained workflow audit passed at commit `4286ac76f44af2317aea2ace6041cea1cba231ab`; its artifact expires on 2026-11-26. The earliest source review is due 2026-11-14. The versioned evidence and operating procedure are in `docs/rag-source-governance.md`; the weekly workflow retains subsequent audits for 90 days.

## Policy RAG Source Governance

On 2026-08-29, the three-document Policy corpus was deployed as `financial-coach-policy-sg@2026-08-29.1` to Knowledge Base `MLOCSOIFML` and data source `WMLKUDKZX5` in `ap-southeast-1`. Ingestion job `PKEVBW4XUB` completed with three new documents indexed, three metadata documents scanned, and zero failed or skipped documents.

The post-ingestion AWS audit passed with zero issues: the Knowledge Base was active, the data source was available, all six expected document and metadata-sidecar objects were present under `policy-controls/documents/`, every checksum and metadata record matched the approved manifest, and no unmanifested object existed. Commit `c6eee3b6e01d7cdc438addd4e20e585e2a213cb1` then passed CI and the AWS release, including live Policy provenance and corpus-pin assertions in the response and persisted trace.

The first retained read-only workflow audit passed with three approved sources and zero issues in run `33231041612`. Artifact `policy-rag-governance-33231041612` has digest `sha256:2ef977fde63649b78ec22374928ccfc39c7e5a30b32a7c68c25e0090496a3d04` and expires on 2026-11-27. All three current sources must be reviewed by 2026-11-27 or replaced by a newly approved corpus version. The versioned evidence and operating procedure are in `docs/policy-rag-governance.md`; the weekly workflow retains subsequent audits for 90 days.

## Operational Alert Notification

On 2026-08-30, the application stack created and confirmed one managed email subscription to the operational SNS topic. The first controlled alarm exercise exposed that the topic policy allowed EventBridge but did not authorize the CloudWatch Alarms service; historical alarm actions showed the same publish denial. The policy was corrected with account and source-ARN restrictions for the exact EventBridge deployment rule and the project alarm prefix.

Controlled test `84399b3a-c683-4d2c-a723-bb6eb2cb6be5` then moved the backend 5xx alarm from `OK` to `ALARM`, recorded a successful SNS action at `2026-08-29T23:59:31.854Z`, and restored the alarm to `OK`. The local privacy-safe artifact records one confirmed subscription without the email address. On 2026-08-30, the Team 9 mailbox operator acknowledged receipt of both the `ALARM` and restoration/`OK` messages, completing end-to-end delivery verification. Operational validation run 33349636155 subsequently retained the automated confirmed-subscription check in its 90-day artifact.

## Open Evidence

- Representative-user validation of explanations and confidence presentation.
- If a Nova Micro change is pursued, first correct or otherwise resolve its repeatable missing-input dependency behavior, then produce a fresh all-green comparison before blinded review.
- Review the exact-version base-image CVE exceptions before they expire on 2026-09-18.
