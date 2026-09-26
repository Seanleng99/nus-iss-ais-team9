# CI/CD Pipeline

## Current delivery path

A push to `main` runs CI and starts `Release to AWS` for the tested commit. The release builds and scans only changed images, tags them with the commit SHA, and updates matching ECS services. A backend update runs Alembic before the service update. Post-deployment smoke verifies unauthenticated denial, scoped automation access, Education citations, independent Policy evidence, corpus pins, and persisted trace provenance. Failed checks restore the task definitions that were updated during the release; ECS deployment circuit breakers cover failed service starts.

The AI task check requires `MODEL_PROVIDER=openai`, `MODEL_ID=gpt-6-luna`, `MODEL_REASONING_EFFORT=low`, both RAG providers set to `local_documents`, exact nonempty Education and Policy corpus versions, and an ECS `OPENAI_API_KEY` secret reference. The key is stored in AWS Secrets Manager and is never a GitHub variable or repository secret.

## Validation workflows

`AWS Operational Validation` runs weekly or on demand against the deployed synthetic demo. It repeats the live OpenAI/RAG cases, measures bounded load and estimated model cost, checks service state, lifecycle controls, dashboard and alarms, and can exercise backend task replacement. Its current model expectation is GPT-6 Luna. This is the required live acceptance evidence for the migration; historical Nova results cannot validate it.

`Education RAG Source Governance` now validates both packaged corpora weekly or on demand. It loads each manifest and exact local files through the production retrievers, checking approval status, provenance, review deadlines, content inspection, and document SHA-256 checksums. It publishes a privacy-safe artifact with both corpus versions and counts. The previous AWS ingestion audits and Bedrock comparison workflow have been retired from active CI; their historical reports remain in the governance and model-selection docs.

## GitHub configuration

`infra/scripts/configure_github.ps1` populates the OIDC role ARNs, ECS cluster/service/task names, ECR repositories, public health and coach URLs, corpus versions, dashboard and alarm identifiers, and bounded validation thresholds. It also sets `SMOKE_BACKEND_API_KEY` in the `demo` environment. The workflow assumes short-lived GitHub OIDC credentials; it does not store AWS access keys.

The deployment role can publish or deploy only the named resources. It no longer needs Bedrock or corpus S3 audit rights. Keep the `demo` environment restricted to `main`. Branch protection and native required reviewers depend on the repository plan.

## Change and acceptance gates

Model, prompt, retrieval, policy, tool, and capability changes require code review and evaluation evidence. The current choice of GPT-6 Luna is documented in [model selection](model-selection.md). Before claiming deployment acceptance, run the repeated synthetic evaluation and check routing, dynamic dependencies, safety, groundedness, citation/provenance, Chinese-language behavior, P95 latency, and actual estimated token cost against the policy thresholds. The direct OpenAI API does not provide Singapore regional processing through its Singapore storage-residency option, so this deployment remains synthetic-data only.
