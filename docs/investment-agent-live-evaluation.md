# Investment Education live integration

Use **CI and LLMSecOps** → **Run workflow** → **main** → check
**Run live integration tests?**. The workflow runs its offline suites first,
then the optional live jobs behind the existing demo environment approval.

The Investment live job runs six synthetic conversations / seven turns against
the deployed backend: four asset definitions, ETF followed by simpler explanation,
diversification, Chinese education, friendly brokerage refusal and prompt injection.
It verifies real Investment model calls for normal answers, current manifest
citations, labelled hybrid content, persisted chat answers/citations and cleanup.
The separate RAG live job makes three real Bedrock Retrieve requests and checks
expected-source hit@5 and approved/current passage provenance. Stable ECS evidence
and deployed SHA are recorded before and after each job.

Definitions and datasets:

- `infra/llmsecops/agent-live-evaluation-specs.json`
- `infra/llmsecops/investment-live-evaluation-cases.jsonl`
- `infra/llmsecops/investment-live-rag-cases.jsonl`

All planned contracts must pass for a live PASS. Failed or missing evidence remains
FAIL/NOT RUN, while the optional job cannot block deployment. No generations are
retried by the harness; rerunning an old workflow attempt is rejected. A fresh
manual Yes selection permits a new bounded run. Automatic CI always selects No.

Download `agent-live-investment`, `agent-live-rag` or the combined
`agent-evaluation-report` for full synthetic Q&A, metrics and acceptance evidence
(retained 90 days). These are real-provider integration contracts, not a 99%
answer-quality claim, semantic review or authenticated browser UI test.

The old self-disabling `investment-agent-live.yml` entry point has been removed.
Its tested Investment/AWS helper functions are reused by the consolidated runner.
Existing post-deployment smoke remains a separate required release check.

See [all jobs, workflow dependencies and execution instructions](agent-test-workflows.md).
