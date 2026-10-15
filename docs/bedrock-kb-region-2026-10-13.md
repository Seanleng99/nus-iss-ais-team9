# Bedrock knowledge bases moved to Tokyo (13 October 2026)

## What happened

From the evening of 13 October 2026 (SGT), every Coach question returned HTTP 503. The AI service logged `workflow.failed` with `RETRIEVAL_ERROR`. The independent Risk and Compliance review could not retrieve policy evidence because Bedrock returned `ThrottlingException`.

The throttle sits on the knowledge bases' embedding model, `cohere.embed-multilingual-v3`, in `ap-southeast-1`:

| Evidence | Result |
|---|---|
| CloudTrail `InvokeModel` by the knowledge bases, 11–12 Oct | ~740 calls, all succeeded; last at 12 Oct ~10:00 UTC |
| Calls between 12 Oct 10:00 UTC and 13 Oct 14:27 UTC | none |
| Calls from 13 Oct 14:27 UTC | all throttled, including the first call and single isolated CLI calls |
| Account changes in that window (CloudTrail quota, billing, Organizations, Bedrock configuration) | none |
| Same model, same account, `ap-northeast-1` | 60 paced and 10 concurrent calls all succeeded |

The Service Quotas console reports 0 for this model's on-demand quotas in every region, including regions where calls succeed. That value is therefore not evidence of the effective limit. The cause is on the AWS side and is being raised with AWS Support.

## Change

Both governed knowledge bases now run in `ap-northeast-1`. Generation (OpenAI) and every other service stay in `ap-southeast-1`.

- `BEDROCK_KB_REGION` (AI service) selects the knowledge bases' region; it defaults to `AWS_REGION`.
- `infra/aws/demo-knowledge-bases.yaml` takes `ResourceNameSuffix` so its account-global IAM names do not clash in a second region. Stack `ai-financial-wellness-coach-kb-tokyo-proof` (`ap-northeast-1`) uses `-ap-northeast-1`. Policy KB `MUOQFTQGCH`, education KB `TSRZVZCH75`, corpus bucket `nus-iss-ais-team9-rag-862124275471-ap-northeast-1`.
- `infra/aws/github-actions-oidc.yaml` takes `KnowledgeBaseRegion` for the deploy and RAG-governance roles.
- The release and RAG governance workflows read the GitHub variable `BEDROCK_KB_REGION`, falling back to `AWS_REGION`.

Before the switch, the application's own retrievers were run against the Tokyo knowledge bases: 19 paced Compliance reviews (three governed policy lookups each), 5 concurrent reviews and 8 education searches all succeeded. Both corpora passed `sync_bedrock_corpora.py` governance at the pinned versions.

## 15 October 2026: throttling follows the account

By 15 October UTC, single `cohere.embed-multilingual-v3` calls from this account were throttled in `ap-northeast-1` and `us-east-1` as well (and Titan Text Embeddings v2 in `ap-northeast-1`); `us-west-2` still answered. The pattern points to an account-level restriction rather than regional capacity, so both retrievers now fall back to the packaged approved corpora during Bedrock outages ([Policy RAG governance](policy-rag-governance.md#availability-fallback-14-october-2026)).

## Switching back

When AWS restores `ap-southeast-1`:

1. Set the GitHub variables `EDUCATION_KNOWLEDGE_BASE_ID=CUCOPYHG5P`, `POLICY_KNOWLEDGE_BASE_ID=QWYTV35QBC`, and remove `BEDROCK_KB_REGION`.
2. Update the GitHub OIDC stack with the Singapore IDs, bucket and an empty `KnowledgeBaseRegion`.
3. Release `main`.

The Tokyo stack's knowledge bases, vector buckets and corpus bucket use `DeletionPolicy: Retain`, so deleting the stack leaves them in place for manual cleanup.
