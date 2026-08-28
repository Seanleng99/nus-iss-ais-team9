# AWS Demo Infrastructure

The repository includes a minimum-size, synthetic-data deployment for AWS account `902552928492` in `ap-southeast-1`:

- `demo-foundation.yaml` creates two public application subnets, two private database subnets, an internet-facing HTTP ALB, security groups, a minimum Single-AZ RDS PostgreSQL instance, three scan-on-push ECR repositories with ten-image retention, a Container-Insights-enabled ECS cluster, Cloud Map, generated service secrets, 30-day log groups, and separate application and AI task roles.
- `demo-application.yaml` creates three minimum-size Fargate services, backend/AI CPU target tracking from one to two tasks, private DNS, task definitions, target groups, ALB routing, a CloudWatch dashboard, seven alarms, SNS alerts, and an ECS deployment-failure EventBridge rule.
- `github-actions-oidc.yaml` creates narrowly scoped image-publishing and ECS-deployment roles using GitHub OIDC. The deployment role can read the operational dashboard, alarms, logs, and scaling configuration for evidence collection, plus audit only the exact Education Knowledge Base and governed S3 prefix.

The public-subnet task design avoids NAT Gateway cost. Tasks receive public IPs for outbound ECR, Secrets Manager, and Bedrock access, but their security groups permit inbound traffic only from the ALB or the calling service. The ALB uses HTTP because no domain and ACM certificate were supplied. Use synthetic data only until HTTPS is configured.

RDS PostgreSQL is encrypted, has no public address, accepts port 5432 only from the backend security group, and uses an RDS-managed master secret. Investment Education retrieves from an externally provisioned Amazon Bedrock Knowledge Base; the CloudFormation stack scopes the AI task role to that knowledge base. The separate managed Policy knowledge base remains deferred.

## Automated Bootstrap

After GitHub and AWS browser authentication, start Docker Desktop and run the bootstrap with the
approved Education Knowledge Base ID:

```powershell
.\infra\scripts\bootstrap_demo.ps1 -EducationKnowledgeBaseId <10-character-kb-id>
.\infra\scripts\configure_github.ps1
```

Add `-AlertEmail address@example.com` to the bootstrap command when email notifications are required, then confirm the AWS SNS subscription. Re-run both scripts after changing these templates so the AWS stacks and operational GitHub variables remain synchronized.

The first script validates the AWS account, discovers the Education data source and governed S3 location, deploys the foundation stack, builds and publishes bootstrap images, creates the ECS services with the corpus pin, and deploys the OIDC roles. The second configures GitHub Actions variables, including the exact knowledge base/data source/bucket/prefix/corpus identifiers, the `demo` environment restricted to `main`, the smoke-test secret, and repository security settings. After the initial push and successful checks, run `protect_main.ps1`; it enables pull-request and CI requirements when the private-repository plan supports branch protection and otherwise reports the plan limitation.

## Deployment Order

1. Confirm the account, region, cost budget, and Bedrock model decision. The initial demo is synthetic-data only.
2. Authenticate with short-lived GitHub and AWS browser sessions.
3. Run `bootstrap_demo.ps1` and wait for all three ECS services to stabilize.
4. Run `configure_github.ps1`, commit, and push the repository to `main`.
5. Successful push CI for the current `main` SHA automatically starts `Release to AWS`.
6. Verify image scanning, deployment, prompt-injection blocking, and rollback.
7. Manually run `AWS Operational Validation`, retain its evidence artifact, and optionally enable the task-replacement exercise.
8. Run `protect_main.ps1` after the first successful workflow creates the required status-check contexts. Upgrade the GitHub plan if branch protection remains unavailable for the private repository.

## Task Configuration Matrix

| Task | Plain environment | Secrets | Task-role access |
|---|---|---|---|
| Frontend | `APP_ENV=demo`, `BACKEND_BASE_URL` | `BACKEND_API_KEY` | None |
| Backend | `APP_ENV=demo`, `AI_SERVICE_BASE_URL`, timeout, database host/name/port, TLS mode, 30-day trace retention | `BACKEND_API_KEY`, `AI_SERVICE_API_KEY`, RDS username/password | None |
| AI service | `APP_ENV=demo`, `MODEL_PROVIDER=bedrock`, `RAG_PROVIDER=bedrock`, model ID, Education Knowledge Base ID, exact corpus version, retrieval threshold, temperatures, prompt version | `AI_SERVICE_API_KEY` | Approved Bedrock profile, destination models, and read-only Education Knowledge Base retrieval |

Do not inject `AI_SERVICE_API_KEY` into Streamlit. Do not place runtime AWS credentials in GitHub or application secrets. ECS tasks obtain AWS permissions from task roles.

## Network Rules

- Internet to demo ALB: TCP 80. Replace this with HTTPS on 443 and redirect 80 after a domain and ACM certificate are available.
- ALB to frontend/backend target security groups: only their container ports.
- Backend to AI: TCP 8001 only.
- Backend to private RDS PostgreSQL: TCP 5432 only.
- ECS tasks use public IPs for low-cost outbound access; security groups still deny direct inbound internet traffic.
- Move application tasks to private subnets plus NAT or VPC endpoints before processing anything beyond synthetic demo data. RDS already uses private database subnets.

## Database Migrations

The backend image contains Alembic and the versioned migration history. Bootstrap runs `alembic upgrade head` once after the ECS application stack is created. Every automatic backend release runs the one-shot ECS migration task, even when no migration path was detected, and checks its exit code before updating the backend service. This makes migration state a deployment invariant and protects against path-classification drift.

Application releases build, scan, and update only services selected by the CI change manifest. Unchanged ECS task definitions remain active. If post-deployment checks fail, explicit rollback restores only services whose new task definitions were successfully deployed; ECS circuit-breaker rollback remains responsible for an individual service update that fails before completion.

Schema changes must remain compatible with the currently running backend during deployment. Service rollback does not automatically reverse a successful database migration; use expand-and-contract changes and create an explicit corrective migration when needed.

## Bedrock Gate

The minimum demo defaults to the `apac.amazon.nova-lite-v1:0` geographic inference profile through the Bedrock Converse API. Nova Lite is profile-only from Singapore, so inference can be routed among the profile's APAC destination Regions. This avoids the unrestricted global profile and third-party model first-use approval. Keep synthetic data until APAC processing is approved, and verify model availability, account entitlement, destinations, quotas, IAM scope, guardrail policy, latency, and cost immediately before deployment because the Bedrock catalog changes over time.

The AI ECS task role has `bedrock:InvokeModel` only for the selected APAC inference profile and its current destination foundation-model ARNs. Foundation-model access is conditioned on that profile. Reconcile the destination list against current AWS profile metadata before deployment because AWS can update profile destinations. The application uses the standard AWS credential chain and must not receive a long-lived Bedrock API key.

## GitHub And OIDC

Use exact OIDC subject claims for the main-branch publisher and `demo` environment deployer. Pass all three ECR repositories and ECS services to `github-actions-oidc.yaml`. The publisher can upload/scan only those repositories; the deployer can update only those services and pass only the named task roles.

The complete GitHub variable list and smoke-test secret are in `docs/cicd-pipeline.md`. Successful push CI for the current `main` SHA automatically starts the release workflow. The weekly `AWS Operational Validation` and `Education RAG Source Governance` workflows use the same short-lived demo-environment OIDC role and produce 90-day privacy-safe evidence. The latter has only read access to the exact governed collection; corpus mutation remains a reviewed operator action using `infra/scripts/rag_source_governance.py`. Native required environment reviewers, branch protection, and GitHub Code Security are unavailable for this private repository on the current GitHub plan; enable them after a plan upgrade. Bandit remains the active Python SAST gate. Secret scanning and push protection are also configured only when the plan supports them.

## Go/No-Go

Do not deploy when any required variable is absent, a database migration fails, a service lacks circuit-breaker rollback, an image has a Critical/High finding above policy, an AI/security evaluation fails, model residency is unresolved for the selected data class, or no previous stable task revision exists for rollback. Do not claim operational readiness until the updated stacks are deployed, an SNS notification path is tested, and a successful AWS operational-evidence artifact is retained.
