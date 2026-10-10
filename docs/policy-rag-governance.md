# Policy RAG Governance

## Current Bedrock corpus governance

The deployed `BedrockPolicyRetriever` retrieves each of the three required Policy sources independently, using public titles and exact source-ID/version/approval filters. It checks retrieved provenance against the checksum-verified manifest packaged at `knowledge/policy_controls`; missing or altered controls fail closed. It does not send personal draft text to Bedrock. `POLICY_CORPUS_VERSION` pins the reviewed version. Release ingests and audits the corpus before activating its pin; weekly **RAG Source Governance** audits both KBs and S3 prefixes through a read-only role. The duplicate Policy-only workflow remains removed. A Policy update requires review, a new version, successful ingestion, and live compliance evaluation. Earlier AWS records below remain historical evidence.

## 9 October 2026 policy and review update

The current source manifest pins `financial-coach-policy-sg@2026-10-09.1`. The
three documents retain their source IDs and have document version `2026-10-09`,
updated checksums and stable clauses `AB-01` through `AB-06`, `EV-01` through
`EV-08`, and `IS-01` through `IS-05`. Approval records the user's authorization
to implement this review. Manifest lifecycle dates use UTC: verification and
approval occurred on 8 October UTC (9 October SGT); the next review is due
6 January 2027 UTC. That source preparation alone was not deployment evidence. The later [Bedrock restoration record](bedrock-kb-restoration-2026-10-09.md) documents ingestion/release checks; it does not establish complete production-model acceptance.

The documents distinguish permitted personal budgeting/goal coaching from
product advice, app record changes from financial-account actions, and authorized
capability handoffs from instruction overrides. They define financial evidence,
shared goal funding, calendar/currency scope, recurrence, partial records,
conversation and preferences, mixed evidence modes, and independent release
review. Missing Education support does not invalidate grounded arithmetic;
missing approved Policy support still prevents model-assisted review.

All three complete documents are supplied on every packaged Policy review. The
retriever does not perform question-dependent passage ranking. Each document
fits the existing 6,000-character context limit. Offline fixtures now carry the
same full document text and all three policy families, while retaining their
explicit fixture corpus label and synthetic expiry. The release workflow derives
the deployment pin from the manifest; the bootstrap template default matches it.

Blocked runs retain fixed reason categories, relevant policy-family clause IDs
and validation failure codes. Clause references identify the family associated
with an accepted category, not proof of the exact offending statement. A failed
review contract has no violation-clause reference. The trace viewer exposes
Policy provenance for blocked and completed runs; neither logs nor public traces
expose rejected prose. See [Risk & Compliance review changes](risk-compliance-review-update-2026-10-09.md).

## Purpose And Boundary

Risk and Compliance uses a Policy RAG collection that is physically and logically separate from Investment Education. Its source of truth is `knowledge/policy_controls/source_manifest.json`, currently pinned as `financial-coach-policy-sg@2026-10-09.1`. The three internal policy documents define financial-coaching advice boundaries, evidence and uncertainty requirements, and retrieved-instruction security for the synthetic demo.

Only Risk and Compliance is allowlisted for `policy_retriever`. Other specialists cannot query the Policy collection, and Compliance cannot query the Education collection directly. Education evidence reaches Compliance through typed specialist results. Policy evidence is not exposed as an end-user education citation; its provenance is retained in the Compliance result and privacy-safe trace.

## Source And Runtime Controls

Each source records an approved internal-rights state, checksum, document version, S3 object and sidecar keys, review dates, and `synthetic_demo_only` usage. The shared strict governance contract rejects unknown metadata, inconsistent lifecycle state, invalid checksums, duplicate keys, and objects outside `policy-controls/documents/`.

The deployed `BedrockPolicyRetriever` accepts only results that:

- meet the configured relevance threshold;
- validate against manifest schema version 2;
- are approved and within their review deadline;
- match `POLICY_CORPUS_VERSION`; and
- carry complete SHA-256 and source provenance.

Retrieved policy text is treated as untrusted data and sanitized before model review. If no current approved policy passes these checks, Risk and Compliance fails closed with `policy_evidence:insufficient`. Provider details are hidden behind a sanitized `policy_retriever` error code.

## Lifecycle And Deployment

The same `infra/scripts/rag_source_governance.py` commands documented for Education apply to the Policy manifest. A safe offline preparation is:

```powershell
python infra/scripts/rag_source_governance.py prepare `
  --manifest knowledge/policy_controls/source_manifest.json `
  --documents-dir knowledge/policy_controls/documents `
  --staging-dir artifacts/policy-rag-staging `
  --output artifacts/policy-rag-prepare.json
```

The historical 29 August 2026 collection used Policy Knowledge Base `MLOCSOIFML`, data source `WMLKUDKZX5`, and corpus version `financial-coach-policy-sg@2026-08-29.1` in `ap-southeast-1`. Ingestion job `PKEVBW4XUB` completed on 2026-08-29 with three new documents indexed, three metadata documents scanned, and zero failed or skipped documents. The post-ingestion audit found all six expected document and sidecar objects, no governance issues, an active Knowledge Base, and an available data source.

CloudFormation pins the exact Knowledge Base ID into the ECS task and limits the task role to the configured Education and Policy knowledge bases. GitHub variables record the Policy knowledge-base ID, data-source ID, corpus version, bucket, and prefix. Release configuration checks require all Policy settings, and post-deployment smoke verifies governed Policy sources and the policy corpus version in both the live response and persisted trace.

The retired Policy governance workflow performed a weekly and on-demand read-only AWS audit. Its OIDC scope could inspect only the approved Policy Knowledge Base and read its exact S3 prefix; it could not upload, delete, or start ingestion. The first historical audit passed with three approved sources and zero issues in [run 33231041612](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33231041612). Artifact `policy-rag-governance-33231041612` was retained until 2026-11-27. Current operating evidence comes from the combined RAG Source Governance workflow, covering packaged files and deployed Bedrock/S3 state.

## Promotion Record And Ongoing Gate

Policy RAG is implemented for the synthetic AWS demo. Commit `c6eee3b6e01d7cdc438addd4e20e585e2a213cb1` passed [CI run 33229618646](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33229618646), and [release run 33229698149](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33229698149) passed configuration validation, immutable-image scanning, deployment, and live health/AI-safety smoke testing on attempt 2. The smoke verified governed Policy provenance and the configured corpus version in both the live response and persisted trace. The separate retained governance audit then passed against the deployed collection.

Promotion of a later Policy corpus version requires reviewed source records, exact-version preparation and apply confirmation, successful ingestion and read-only AWS audit, updated runtime pins, a passing release smoke, and retained governance evidence. Review the current three sources by 2027-01-06 or publish a newly approved corpus version before that deadline.
