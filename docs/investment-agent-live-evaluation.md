# Investment Education live integration

**Release to AWS** runs Investment and RAG contracts after deploying the tested
current main SHA and passing health/safety smoke. Both stages are required;
failed or incomplete evidence fails the release and rolls changed services back.
The deployment job retains the existing `demo` environment and release lock.

Investment runs six synthetic conversations / seven turns against the deployed
backend: four asset definitions, ETF followed by a simpler explanation,
diversification, Chinese education, brokerage refusal and prompt injection.
It verifies real Investment model calls for normal answers, current manifest
citations, labelled hybrid content, persisted chat answers/citations and cleanup.
RAG makes three real Bedrock Retrieve requests and checks expected-source hit@5
and approved/current passage provenance. Test/deployed SHA must match the release;
stable ECS evidence is recorded before and after execution.

Definitions and datasets:

- `infra/llmsecops/agent-live-evaluation-specs.json`
- `infra/llmsecops/investment-live-evaluation-cases.jsonl`
- `infra/llmsecops/investment-live-rag-cases.jsonl`

Every planned contract must pass. Each dataset runs once without harness
generation retries, retaining its existing token limits. Rerunning an old paid
release attempt is rejected; fresh successful main CI is required for a new run.
PR/manual/scheduled CI executes offline checks without paid-live inputs.

Download **`release-live-acceptance-<run_id>`** from Release for full synthetic
Q&A, source hashes, usage and aggregate acceptance evidence (90 days). These
real-provider contracts do not establish 99% answer quality, semantic review or
authenticated browser UI acceptance.

The old `investment-agent-live.yml` entry point is removed. Its tested helper
functions remain reused by the consolidated runner. Release additionally requires
all 19 fairness pairs once, all other agent datasets and live security regressions.

See [workflow ownership](agent-test-workflows.md) and
[required live release acceptance](post-deployment-acceptance.md).
