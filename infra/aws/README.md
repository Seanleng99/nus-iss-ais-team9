# AWS Demo Infrastructure

The synthetic-data demo runs the frontend, backend, and AI service on ECS Fargate in `ap-southeast-1`. `demo-foundation.yaml` provisions networking, RDS, Cognito, ECR, ECS, CloudFront/ALB, logging, and generated service credentials; it grants the ECS execution role access to an existing OpenAI API-key secret. `demo-application.yaml` deploys the services and operational alarms. `github-actions-oidc.yaml` limits GitHub image publishing and ECS deployment to short-lived OIDC roles.

The AI task uses `MODEL_PROVIDER=openai`, `MODEL_ID=gpt-6-luna`, and `MODEL_REASONING_EFFORT=medium`. Its `OPENAI_API_KEY` comes from the existing Secrets Manager secret via the ECS task execution role. Both retrieval providers use `local_documents`; the image packages reviewed Education and Policy corpora. The task role has no model-invocation or knowledge-base permissions. The retired `demo-knowledge-bases.yaml` template is retained solely as historical infrastructure source and is not part of bootstrap or release.

## API-key setup and bootstrap

Before bootstrap, create or update the existing Secrets Manager secret `ai-financial-wellness-coach/demo/openai-api-key` with JSON `{"openai-api-key":"<your OpenAI API key>"}` using a secure operator session. Bootstrap verifies that it is populated, resolves its ARN, and passes that ARN to both stacks. The foundation template does not create a duplicate secret. Do not commit or send the key in chat. Keep `.env.example` blank; use a private shell environment or ignored `.env` for local runs.

```powershell
.\infra\scripts\bootstrap_demo.ps1
.\infra\scripts\configure_github.ps1
```

The first script validates the AWS account, builds and publishes the images, creates the ECS services with exact corpus pins, and deploys OIDC roles. The second configures GitHub Actions variables, the `demo` environment, and the smoke-test secret. Neither script calls Bedrock. Add `-AlertEmail address@example.com` to bootstrap to request SNS notifications, then confirm the subscription. Re-run the scripts when stack templates or deployment variables change.

For account migration, follow [the migration runbook](../../docs/aws-account-migration.md) before bootstrap. Use `-DatabaseSnapshotIdentifier` for a destination-owned snapshot. The foundation creates a new Cognito pool and RDS master secret. Keep the previous identity pool available until migrated users confirm sign-in and record access.

## Release and operational checks

A successful push CI on the current `main` SHA starts `Release to AWS`. The release verifies the rendered AI task selects OpenAI and GPT-6 Luna, both local corpora are pinned, and the API-key secret is referenced. It then updates only changed services, runs backend migrations, performs authenticated smoke checks, and rolls back updated task definitions if checks fail. Every deployment uses immutable commit-SHA image tags.

The AI request ceiling is `MAX_MODEL_TOKENS_PER_RUN=80000` and the application accepts only prompt set v8. Startup rejects a legacy prompt override. Before rendering, release loads the checked-in `apps/ai-service/app/core/model-role-policy.json` and publishes its canonical JSON as `MODEL_ROLE_OVERRIDES`. Rendering replaces any inherited role settings; verification rejects absent or changed overrides. Bootstrap and `.env.example` carry the same policy, checked by regression tests. Financial writers use medium/3,200, Education medium/4,000 and Compliance medium/3,000 reasoning/output policies. Routing/planning retain their smaller role limits; the global default is medium/3,200. Increasing the total ceiling does not relax review, tool permissions, call limits or deadlines.

Run `AWS Operational Validation` after the first deployment to collect repeated synthetic model/RAG results, bounded load data, ECS state, dashboard and alarm checks, and lifecycle evidence. The existing historical Bedrock measurements do not count as GPT-6 Luna acceptance. See [model selection](../../docs/model-selection.md) and [CI/CD](../../docs/cicd-pipeline.md).

The basic model smoke uses a fresh synthetic user/session and a read-only disposable-income calculation with explicit monthly recurrence. It requires the Budget writer, checks the known SGD 2,500 result, and verifies v8 and canonical role settings in both response and persisted trace telemetry. A request to create a budget can instead use `budget_capture`, so it cannot establish that the narrative Budget writer ran. See [operations](../../docs/operations.md) for the 6 October smoke failure and rollback evidence.

## Security and network

The frontend never receives the OpenAI or AI-service API keys. The backend uses a private AI-service endpoint and owner-scoped PostgreSQL records. RDS is encrypted in private subnets and accepts traffic only from the backend security group. The public-subnet ECS design avoids NAT cost for the synthetic demo; task security groups deny direct inbound internet traffic. Move tasks to private networking and complete a fresh privacy/location review before processing real financial data. The direct OpenAI API's Singapore data-residency option covers storage, not regional processing.

The CloudFront-to-ALB path uses a generated origin-verification header and AWS's maintained CloudFront origin-facing prefix list. `harden_edge.ps1` enables those restrictions and supports custom-domain HTTPS when matching ACM certificates and DNS are available. `activate_user_auth.ps1` is for staged pre-authentication stacks only; fresh bootstrap already includes Cognito. Branch protection and GitHub environment reviewer controls depend on the repository plan.

Do not claim operational readiness until login, owner isolation, alarm delivery, rollback, live evaluation, and the required TLS/origin controls have been demonstrated. Keep the demo synthetic until the data-processing geography and privacy posture are approved.
