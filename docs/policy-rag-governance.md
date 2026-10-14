# Policy RAG Governance

## Current Bedrock corpus governance

The deployed `BedrockPolicyRetriever` retrieves each of the three required Policy sources independently, using public titles and exact source-ID/version/approval filters. It checks returned source metadata against the checksum-verified manifest packaged at `knowledge/policy_controls` and fails retrieval when a required source has no matching chunk. It does not send personal draft text to Bedrock. `POLICY_CORPUS_VERSION` pins the reviewed version. Release ingests and audits the corpus before activating its pin; weekly **RAG Source Governance** audits both KBs and S3 prefixes through a read-only role. A Policy update requires review, a new version, successful ingestion and live compliance evaluation.

## Availability fallback (14 October 2026)

When Bedrock is unavailable — `ThrottlingException`, `ServiceUnavailableException`, `InternalServerException`, `DependencyFailedException`, `ServiceQuotaExceededException`, or a connection/read timeout — `BedrockPolicyRetriever` returns the three full documents from the packaged, checksum-verified manifest instead of failing every review. This is the same copy Bedrock results are already matched against, and it still enforces the pinned corpus version and review deadline. Each fallback logs `policy.retrieval.fallback` with the error code as `reason_code`.

Missing or mismatched Bedrock evidence, access-denied, validation and not-found errors do not fall back; they still fail closed. Background: Cohere embedding throttling in `ap-southeast-1` from 13 October blocked every Coach answer ([Bedrock KB region](bedrock-kb-region-2026-10-13.md)).

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

Local-document and fixture providers carry all three full packaged policies, each
within the existing 6,000-character context limit. Bedrock queries up to 20 chunks
per required source and joins unique matching chunks rather than ranking by the
personal question. Returned metadata does not prove full document coverage or
byte equality of returned text. Compliance then removes unsafe or oversized
contexts and blocks when none remain; it does not recheck all three source IDs
after that filtering. Complete mandatory-source coverage after sanitization is
therefore a remaining validation boundary. Fixtures retain their explicit corpus
label and synthetic expiry. Release derives the deployment pin from the manifest;
the bootstrap template default matches it.

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

Use the active environment's Policy Knowledge Base and data-source IDs with the exact reviewed corpus pin. The [Bedrock restoration record](bedrock-kb-restoration-2026-10-09.md) retains the current path's ingestion/release checks; earlier corpus versions do not establish acceptance of the current policies.

CloudFormation pins the exact Knowledge Base ID into the ECS task and limits the task role to the configured Education and Policy knowledge bases. GitHub variables record the Policy knowledge-base ID, data-source ID, corpus version, bucket, and prefix. Release configuration checks require all Policy settings, and post-deployment smoke verifies governed Policy sources and the policy corpus version in both the live response and persisted trace.

Current operating evidence comes from the combined RAG Source Governance workflow, covering packaged files and deployed Bedrock/S3 state. Its read-only OIDC role can inspect approved Knowledge Bases and exact S3 prefixes; it cannot upload, delete or start ingestion.

## Promotion Record And Ongoing Gate

Policy RAG is implemented for the synthetic AWS demo. Release smoke verifies governed Policy provenance and the exact corpus version in both the live response and persisted trace. Passing ingestion, governance or smoke establishes those controls at the recorded revision; it does not establish complete semantic answer acceptance.

Promotion of a later Policy corpus version requires reviewed source records, exact-version preparation and apply confirmation, successful ingestion and read-only AWS audit, updated runtime pins, a passing release smoke, and retained governance evidence. Review the current three sources by 2027-01-06 or publish a newly approved corpus version before that deadline.
