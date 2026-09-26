# Education RAG Source Governance

## Current packaged-corpus governance

The deployed Education retriever reads the ten approved documents and `source_manifest.json` from the AI image at `knowledge/investment_education`. It verifies manifest approval and review deadlines, canonical URL allowlists, UTF-8 text, content inspection, and SHA-256 checksums before serving evidence. `EDUCATION_CORPUS_VERSION` pins the exact reviewed version. For each release SHA, the release derives Education and Policy pins from their manifests, injects and verifies them on the task definition, and passes the same values to the post-deploy smoke check. The weekly `rag-source-governance.yml` workflow validates both packaged corpora offline with `contents: read` and retains evidence; it does not assume an AWS OIDC role or audit S3. A source change requires a reviewed manifest, new corpus version, rebuilt image, and passing retrieval/evaluation gates. Bedrock ingestion and AWS audit commands below are historical optional provider tooling, not prerequisites for the local-packaged deployment.

## Historical AWS ingestion and governance

## Governed Corpus

The governed Education knowledge base uses the versioned manifest at `knowledge/investment_education/source_manifest.json` as its source of truth. Corpus version `investment-education-sg@2026-09-26.1` contains ten approved documents for the synthetic-data demo: six existing public-reference documents and four project-authored MoneySense paraphrases. It supports Investment Education directly and conditional Budget or Goal Strategy explanations through the orchestrator. Approval does not grant a production-content licence or authorize real personal financial data.

Each manifest entry records:

- stable source ID, title, issuing organization, and canonical HTTPS URL;
- publication and document versions; `published_at` records the source page’s displayed last-updated date when that is the available date, not necessarily its original publication date;
- exact SHA-256 document checksum and S3 document/metadata keys;
- source, content, and public-reference rights review states;
- Singapore jurisdiction and `synthetic_demo_only` usage scope;
- last verification, next review, and withdrawal dates; and
- ingestion approval and topics.

The strict Pydantic contract rejects unknown fields, duplicate IDs or keys, invalid checksums, objects outside the approved prefix, inconsistent approval/withdrawal states, and metadata keys that do not pair with a document.

The four summaries captured on 2026-09-26 (`moneysense_compound_interest.md`, `moneysense_managing_money.md`, `moneysense_managing_debt.md`, and `moneysense_investment_scams.md`) are concise, project-authored paraphrases, not full source documents or purported verbatim copies. Their scoped approval reference records assistant-verified public-source summary review for the user-requested educational expansion; it does not claim a separate human sign-off. They are limited to `synthetic_demo_only` and are due for review no later than 2026-11-14.

## Lifecycle Commands

`infra/scripts/rag_source_governance.py` retains optional Bedrock provider operations alongside offline governance operations:

| Operation | Purpose | Mutation protection |
|---|---|---|
| `validate` | Validate manifest structure, approval, and freshness offline | Read-only |
| `prepare` | Check local UTF-8 documents, checksums, and indirect-injection controls; create Bedrock sidecars | Writes only to the requested staging directory |
| `audit-aws` | Compare S3, Bedrock catalog, latest ingestion, sidecars, checksums, freshness, and withdrawn state with the manifest | Read-only AWS access |
| `apply` | Upload an entirely reviewed active corpus and synchronize the data source | Requires the exact corpus version as confirmation |
| `publish-metadata` | Migrate verified existing documents to governed sidecars and synchronize | Verifies document bytes first and requires the exact corpus version |
| `withdraw` | Delete one reviewed-withdrawn document and sidecar, then synchronize | Manifest must already mark it withdrawn and confirmation must equal its source ID |

The Bedrock apply and metadata operations reject a document when its byte checksum differs, it is not UTF-8, its source review is expired, or ingestion guardrails identify embedded instructions. They do not silently sanitize authoritative source content. These provider operations are not required to build or deploy the locally packaged corpus; a new corpus requires a rebuilt image and passing governance validation.

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

The ECS task definition pins `EDUCATION_CORPUS_VERSION`, derived from the Education manifest at the release SHA. The deployed local-document retriever loads the approved documents and manifest from the image and verifies the configured corpus version before serving evidence. The historical Bedrock retriever accepts a chunk only when its metadata:

- validates against manifest schema version 2;
- is approved for the synthetic demo;
- matches the configured corpus version;
- has not passed its review deadline; and
- carries a valid SHA-256 checksum and required provenance.

Accepted citations expose document version, checksum, corpus version, and review deadline through the AI and backend APIs. Privacy-safe orchestration traces additionally record the retrieval consumer, dependency edge, corpus versions, and source/version/checksum tuples used by a response. Conditional retrieval queries contain canonical topic labels rather than personal financial amounts. Evidence-gap traces still record the configured corpus version through the consuming Investment Education, Budget, or Goal Strategy result.

## AWS Evidence

On 2026-08-28, governed metadata was published to the then-current six documents and ingestion job `D4C4MMUERE` completed successfully. The 2026-09-26 corpus expansion has not been synchronized to AWS; the recorded evidence below applies to the earlier six-document corpus only. Bedrock scanned six documents, modified six metadata documents, and reported zero failed documents. The post-ingestion audit verified:

- active knowledge base `X2BXBRYX2X` and available data source `H6D6Z2RUL2`;
- 12 expected S3 objects and no unmanifested object under the approved prefix;
- six matching document SHA-256 checksums and sidecars;
- corpus version `investment-education-sg@2026-08-28.1` on retrieved chunks;
- Singapore source Region with the knowledge base's configured Cohere multilingual embedding model; and
- earliest source review due date of 2026-11-14, with zero governance issues.

The AWS identifiers are demo evidence, not reusable defaults for another account.

## Scheduled Gate And Review Procedure

`.github/workflows/rag-source-governance.yml` runs weekly and on demand as an offline packaged-corpus validator with `contents: read`; it retains its JSON evidence for 90 days. It does not use OIDC or access AWS or S3. The AWS ingestion and audit commands above remain available as historical optional provider tooling.

Before the review deadline, the owner must re-verify each canonical source, review content changes and usage rights, capture new bytes and checksums when needed, increment the corpus version, rerun offline and live retrieval evaluations, and approve the manifest change. A new corpus requires a rebuilt image and passing governance validation before release; Bedrock ingestion is not a deployment prerequisite. If a source is superseded, unsafe, or withdrawn, mark it withdrawn in a reviewed manifest before using the optional provider withdrawal command. A failed or stale validation blocks corpus promotion and requires investigation; it must not be bypassed by changing the runtime version alone.
