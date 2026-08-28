# Education RAG Source Governance

## Governed Corpus

The Investment Education knowledge base uses the versioned manifest at `knowledge/investment_education/source_manifest.json` as its source of truth. Corpus version `investment-education-sg@2026-08-28.1` contains six approved public-reference documents for the synthetic-data demo. Approval does not grant a production-content licence or authorize real personal financial data.

Each manifest entry records:

- stable source ID, title, issuing organization, and canonical HTTPS URL;
- publication and document versions;
- exact SHA-256 document checksum and S3 document/metadata keys;
- source, content, and public-reference rights review states;
- Singapore jurisdiction and `synthetic_demo_only` usage scope;
- last verification, next review, and withdrawal dates; and
- ingestion approval and topics.

The strict Pydantic contract rejects unknown fields, duplicate IDs or keys, invalid checksums, objects outside the approved prefix, inconsistent approval/withdrawal states, and metadata keys that do not pair with a document.

## Lifecycle Commands

`infra/scripts/rag_source_governance.py` provides six fail-closed operations:

| Operation | Purpose | Mutation protection |
|---|---|---|
| `validate` | Validate manifest structure, approval, and freshness offline | Read-only |
| `prepare` | Check local UTF-8 documents, checksums, and indirect-injection controls; create Bedrock sidecars | Writes only to the requested staging directory |
| `audit-aws` | Compare S3, Bedrock catalog, latest ingestion, sidecars, checksums, freshness, and withdrawn state with the manifest | Read-only AWS access |
| `apply` | Upload an entirely reviewed active corpus and synchronize the data source | Requires the exact corpus version as confirmation |
| `publish-metadata` | Migrate verified existing documents to governed sidecars and synchronize | Verifies document bytes first and requires the exact corpus version |
| `withdraw` | Delete one reviewed-withdrawn document and sidecar, then synchronize | Manifest must already mark it withdrawn and confirmation must equal its source ID |

The apply and metadata operations reject a document when its byte checksum differs, it is not UTF-8, its source review is expired, or ingestion guardrails identify embedded instructions. They do not silently sanitize authoritative source content.

Example read-only audit:

```powershell
python infra/scripts/rag_source_governance.py audit-aws `
  --manifest knowledge/investment_education/source_manifest.json `
  --knowledge-base-id "$env:EDUCATION_KNOWLEDGE_BASE_ID" `
  --data-source-id "$env:EDUCATION_DATA_SOURCE_ID" `
  --bucket "$env:EDUCATION_SOURCE_BUCKET" `
  --prefix "investment-education/documents/" `
  --region ap-southeast-1 `
  --output artifacts/rag-source-governance.json
```

## Runtime Enforcement And Traceability

The ECS task definition pins `EDUCATION_CORPUS_VERSION`. The Bedrock retriever accepts a chunk only when its metadata:

- validates against manifest schema version 2;
- is approved for the synthetic demo;
- matches the configured corpus version;
- has not passed its review deadline; and
- carries a valid SHA-256 checksum and required provenance.

Accepted citations expose document version, checksum, corpus version, and review deadline through the AI and backend APIs. Privacy-safe orchestration traces additionally record the corpus versions and source/version/checksum tuples used by a response. Evidence-gap traces still record the configured corpus version through the Investment Education result.

## AWS Evidence

On 2026-08-28, governed metadata was published to the existing six documents and ingestion job `D4C4MMUERE` completed successfully. Bedrock scanned six documents, modified six metadata documents, and reported zero failed documents. The post-ingestion audit verified:

- active knowledge base `X2BXBRYX2X` and available data source `H6D6Z2RUL2`;
- 12 expected S3 objects and no unmanifested object under the approved prefix;
- six matching document SHA-256 checksums and sidecars;
- corpus version `investment-education-sg@2026-08-28.1` on retrieved chunks;
- Singapore source Region with the knowledge base's configured Cohere multilingual embedding model; and
- earliest source review due date of 2026-11-14, with zero governance issues.

The AWS identifiers are demo evidence, not reusable defaults for another account.

## Scheduled Gate And Review Procedure

`.github/workflows/rag-source-governance.yml` runs weekly and on demand. Its OIDC role can inspect only the approved knowledge base and read only the governed S3 prefix. It cannot upload, delete, or start ingestion. The workflow retains its privacy-safe JSON evidence for 90 days.

Before the review deadline, the owner must re-verify each canonical source, review content changes and usage rights, capture new bytes and checksums when needed, increment the corpus version, rerun offline and live retrieval evaluations, and approve the manifest change. If a source is superseded, unsafe, or withdrawn, mark it withdrawn in a reviewed manifest before executing the exact-ID withdrawal command. A failed or stale audit blocks corpus promotion and requires investigation; it must not be bypassed by changing the runtime version alone.
