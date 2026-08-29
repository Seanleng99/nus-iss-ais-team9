# Policy RAG Governance

## Purpose And Boundary

Risk and Compliance uses a Policy RAG collection that is physically and logically separate from Investment Education. Its source of truth is `knowledge/policy_controls/source_manifest.json`, pinned as `financial-coach-policy-sg@2026-08-29.1`. The three internal policy documents define financial-coaching advice boundaries, evidence and uncertainty requirements, and retrieved-instruction security for the synthetic demo.

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

The deployed collection uses Policy Knowledge Base `MLOCSOIFML`, data source `WMLKUDKZX5`, and corpus version `financial-coach-policy-sg@2026-08-29.1` in `ap-southeast-1`. Ingestion job `PKEVBW4XUB` completed on 2026-08-29 with three new documents indexed, three metadata documents scanned, and zero failed or skipped documents. The post-ingestion audit found all six expected document and sidecar objects, no governance issues, an active Knowledge Base, and an available data source.

CloudFormation pins the exact Knowledge Base ID into the ECS task and limits the task role to the configured Education and Policy knowledge bases. GitHub variables record the Policy knowledge-base ID, data-source ID, corpus version, bucket, and prefix. Release configuration checks require all Policy settings, and post-deployment smoke verifies governed Policy sources and the policy corpus version in both the live response and persisted trace.

`.github/workflows/policy-rag-source-governance.yml` performs a weekly and on-demand read-only audit. Its OIDC scope can inspect only the approved Policy Knowledge Base and read its exact S3 prefix; it cannot upload, delete, or start ingestion. The first retained audit passed with three approved sources and zero issues in [run 33231041612](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33231041612). Artifact `policy-rag-governance-33231041612` is retained until 2026-11-27; subsequent successful runs replace it as the current operating evidence.

## Promotion Record And Ongoing Gate

Policy RAG is implemented for the synthetic AWS demo. Commit `c6eee3b6e01d7cdc438addd4e20e585e2a213cb1` passed [CI run 33229618646](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33229618646), and [release run 33229698149](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/33229698149) passed configuration validation, immutable-image scanning, deployment, and live health/AI-safety smoke testing on attempt 2. The smoke verified governed Policy provenance and the configured corpus version in both the live response and persisted trace. The separate retained governance audit then passed against the deployed collection.

Promotion of a later Policy corpus version requires reviewed source records, exact-version preparation and apply confirmation, successful ingestion and read-only AWS audit, updated runtime pins, a passing release smoke, and retained governance evidence. Review the current three sources by 2026-11-27 or publish a newly approved corpus version before that deadline.
