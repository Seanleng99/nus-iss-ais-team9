# CI/CD Pipeline

## Current delivery path

A push to `main` runs CI and starts `Release to AWS` only after CI succeeds for the current commit. Application releases build and scan all three service images from that tested SHA so recovery also includes earlier fixes. The backend deployment runs Alembic before the service update. Post-deployment smoke verifies unauthenticated denial, scoped automation access, Education citations, independent Policy evidence, corpus pins, and persisted trace provenance. Failed checks restore the task definitions that were updated during the release; ECS deployment circuit breakers cover failed service starts.

Main pushes classify all changes since the last successful `Deploy demo environment`
job, rather than just the newest push. Failed CI or deployment leaves application
changes pending; a successful release with a skipped deployment does not advance
the baseline. This lets a later security or pipeline fix release the pending
application changes. If no deployment is retained or its commit is outside the
checkout history, CI runs every service check. Pull requests retain their normal
base-to-head comparison. The change-manifest artifact also records the deployment
baseline used for classification.

The AI task check requires `MODEL_PROVIDER=openai`, `MODEL_ID=gpt-6-luna`, medium default reasoning with the reviewed role overrides, the [packaged current prompt identity](current-prompt-contract.md), both RAG providers set to `local_documents`, exact nonempty Education and Policy corpus versions, and an ECS `OPENAI_API_KEY` secret reference. The key is stored in AWS Secrets Manager and is never a GitHub variable or repository secret.

## Validation workflows

`AWS Operational Validation` runs weekly or on demand against the deployed synthetic demo. It repeats the live OpenAI/RAG cases, measures bounded load and estimated model cost, checks service state, lifecycle controls, dashboard and alarms, and can exercise backend task replacement. Its current model expectation is GPT-6 Luna. This is the required live acceptance evidence for the migration; historical Nova results cannot validate it.

`RAG Source Governance` validates both packaged corpora weekly or on demand. It loads each manifest and exact local files through the production retrievers, checking approval status, provenance, review deadlines, content inspection, and document SHA-256 checksums. It publishes a privacy-safe artifact with both corpus versions and counts. The duplicate Policy workflow and retired Bedrock comparison notice have been removed; their historical reports remain in the governance and model-selection docs.

The five Agent workflows execute their owned offline tests; CI runs the remaining AI tests and the conversational contracts separately. `Project OWASP Security Scan` is reusable from CI and adds committed Promptfoo security cases across all agents and the router. Its backend/frontend companion test runs have been removed because the service CI jobs already execute those tests. Both the required Agent gate and the OWASP scan must pass before CI builds release containers. See [agent test ownership](agent-test-workflows.md) and [security scan coverage](project-security-scan.md).

`Budget Live Acceptance` remains an optional manual check of nine focused deployed-model cases and multi-turn confirmation behaviour. `Final Assessment` remains a manual academic evidence inventory that requires successful main CI and calls `AWS Operational Validation`; it is not part of every release.

## Workflow inventory

The workflow audit keeps the following responsibilities:

| Workflow | Purpose and trigger |
| --- | --- |
| CI and LLMSecOps | Automatic PR/main validation, weekly checks and manual CI |
| Spending, Budget, Goal, Investment, Risk & Compliance Agent Tests | Reusable test owners called by CI; focused manual runs |
| Agent Test Suite | Internal reusable runner; installs dependencies and publishes each selected pytest report |
| Project OWASP Security Scan | Reusable offline security scenarios; optional paid live scan only by manual main dispatch |
| Release to AWS | Deployment after successful push CI at the current main SHA |
| RAG Source Governance | Weekly/manual freshness and integrity checks for both packaged corpora |
| AWS Operational Validation | Weekly/manual deployed-model, lifecycle, load and operational evidence |
| Budget Live Acceptance | Manual focused deployed-model and confirmation-flow acceptance |
| Final Assessment | Manual academic evidence inventory and operational validation wrapper |
| Dependabot Updates | GitHub-managed dependency maintenance |

The duplicate **Policy RAG Source Governance** and notice-only **Historical
Bedrock Model Comparison** definitions have been removed. Historical reports
remain available; the assessment manifest now references current prompt/model
policy evidence and the combined governance workflow.

## GitHub configuration

`infra/scripts/configure_github.ps1` populates the OIDC role ARNs, ECS cluster/service/task names, ECR repositories, public health and coach URLs, corpus versions, dashboard and alarm identifiers, and bounded validation thresholds. It also sets `SMOKE_BACKEND_API_KEY` in the `demo` environment. The workflow assumes short-lived GitHub OIDC credentials; it does not store AWS access keys.

The deployment role can publish or deploy only the named resources. It no longer needs Bedrock or corpus S3 audit rights. Keep the `demo` environment restricted to `main`. Branch protection and native required reviewers depend on the repository plan.

## Change and acceptance gates

Model, prompt, retrieval, policy, tool, and capability changes require code review and evaluation evidence. The current choice of GPT-6 Luna is documented in [model selection](model-selection.md). Before claiming deployment acceptance, run the repeated synthetic evaluation and check routing, dynamic dependencies, safety, groundedness, citation/provenance, Chinese-language behavior, P95 latency, and actual estimated token cost against the policy thresholds. The direct OpenAI API does not provide Singapore regional processing through its Singapore storage-residency option, so this deployment remains synthetic-data only.
