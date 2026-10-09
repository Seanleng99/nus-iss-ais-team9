# Bedrock KB restoration, 9 October 2026

Both governed corpora were uploaded to their existing S3 data sources, ingested into the retained Bedrock Knowledge Bases, and audited against the checked-in source manifests. Answer generation uses the direct OpenAI API with `gpt-6-luna`. Bedrock supplies retrieval and the KB's Cohere embeddings.

| Corpus | Knowledge Base | Data source | Approved documents | Corpus version | Release ingestion job |
| --- | --- | --- | --- | --- | --- |
| Education | `CUCOPYHG5P` | `BXVNX4OULE` | 10 | `investment-education-sg@2026-09-27.2` | `9HOAJQS3MH` |
| Policy | `QWYTV35QBC` | `WH5OQ7UAPT` | 3 | `financial-coach-policy-sg@2026-10-09.1` | `3VXLDIXAIC` |

Both release ingestion jobs completed with zero failed or skipped documents. Remote audits found matching document checksums and metadata, approved and current review states, and no unmanifested S3 objects. A separate live retrieval check found indexed passages for every approved source and matching document versions and checksums. The Policy adapter carried all three control families.

The release checks both local manifests before uploading either corpus, waits for ingestion, audits both KBs, and then sets the ECS provider and corpus pins. The AI task has `bedrock:Retrieve` on the two KBs. Release can upload to their approved prefixes and start ingestion; the weekly governance role is read-only. Policy retrieval uses public policy titles and exact source filters, and checks the approved source identity before carrying all three controls into review.

Deployment passed. The tested release includes `45ea010` and `7fe7eed`, the KB restoration, and the validation fixes, at build commit `dc01ebd5403c8a447be66dd1ebbfc21da039a393`. The running AI service is `coach-ai:62`, with one running task using that image. A final ECS check confirmed both Bedrock provider settings, both KB IDs and corpus pins, and direct OpenAI generation with `gpt-6-luna`. CloudWatch recorded 17 retrieval requests from the running task, covering both Education and Policy KBs.

The deployed smoke gate passed frontend and backend health, the user authentication boundary, OpenAI-backed coaching, prompt-injection blocking, governed Education and Policy retrieval, conditional Budget Education retrieval, and backend persistence. The live retrieval checks also validated source/version evidence in persisted traces.

Evidence:

- [Successful CI](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/37878266503), including application, agent, infrastructure, security, integration, and container checks.
- [Successful read-only live KB governance](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/37878116504).
- [Successful AWS release and ingestion reports](https://github.com/Seanleng99/nus-iss-ais-team9/actions/runs/37878722281), retained in `bedrock-corpus-governance-37878722281` for 90 days.
- Local operator evidence in `artifacts/bedrock-restore-2026-10-09/`, including initial ingestion, source audits, per-source live retrieval, and the downloaded release reports.

The security evaluator also accepts the approved fixed refusal explanations and bounded review metadata. It still rejects arbitrary prose, private data, exposed sources, and unknown review codes. All 75 offline security cases passed, including regressions for tampered withheld payloads.
