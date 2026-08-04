# AWS Demo Infrastructure

The repository includes a minimum-size, synthetic-data deployment for AWS account `902552928492` in `ap-southeast-1`:

- `demo-foundation.yaml` creates two public subnets, an internet-facing HTTP ALB, security groups, three ECR repositories, an ECS cluster, Cloud Map, generated service secrets, seven-day log groups, and separate application and AI task roles.
- `demo-application.yaml` creates three one-task Fargate services, private DNS for backend-to-AI and frontend-to-backend calls, task definitions, target groups, and ALB routing.
- `github-actions-oidc.yaml` creates narrowly scoped image-publishing and ECS-deployment roles using GitHub OIDC.

The public-subnet task design avoids NAT Gateway cost. Tasks receive public IPs for outbound ECR, Secrets Manager, and Bedrock access, but their security groups permit inbound traffic only from the ALB or the calling service. The ALB uses HTTP because no domain and ACM certificate were supplied. Use synthetic data only until HTTPS is configured.

RDS and a managed vector service are intentionally omitted because the current backend does not persist records and the current compliance retriever uses packaged controlled data. Add those services only when their application integrations are implemented.

## Automated Bootstrap

After GitHub and AWS browser authentication, start Docker Desktop and run:

```powershell
.\infra\scripts\bootstrap_demo.ps1
.\infra\scripts\configure_github.ps1
```

The first script validates the AWS account, deploys the foundation stack, builds and publishes bootstrap images, creates the ECS services, and deploys the OIDC roles. The second configures GitHub Actions variables, the `demo` environment restricted to `main`, the protected smoke-test secret, and repository security settings. After the initial push and successful checks, run `protect_main.ps1` to require pull requests and CI checks.

## Deployment Order

1. Confirm the account, region, cost budget, and Bedrock model decision. The initial demo is synthetic-data only.
2. Authenticate with short-lived GitHub and AWS browser sessions.
3. Run `bootstrap_demo.ps1` and wait for all three ECS services to stabilize.
4. Run `configure_github.ps1`, commit, and push the repository to `main`.
5. Verify CI, image scanning, protected deployment, prompt-injection blocking, and rollback.
6. Run `protect_main.ps1` after the first successful workflow creates the required status-check contexts.

## Task Configuration Matrix

| Task | Plain environment | Secrets | Task-role access |
|---|---|---|---|
| Frontend | `APP_ENV=demo`, `BACKEND_BASE_URL` | `BACKEND_API_KEY` | None |
| Backend | `APP_ENV=demo`, `AI_SERVICE_BASE_URL`, timeout, non-operational database placeholder | `BACKEND_API_KEY`, `AI_SERVICE_API_KEY` | None |
| AI service | `APP_ENV=demo`, `MODEL_PROVIDER=bedrock`, model ID, temperatures, prompt version | `AI_SERVICE_API_KEY` | Approved Bedrock profile and destination models |

Do not inject `AI_SERVICE_API_KEY` into Streamlit. Do not place runtime AWS credentials in GitHub or application secrets. ECS tasks obtain AWS permissions from task roles.

## Network Rules

- Internet to demo ALB: TCP 80. Replace this with HTTPS on 443 and redirect 80 after a domain and ACM certificate are available.
- ALB to frontend/backend target security groups: only their container ports.
- Backend to AI: TCP 8001 only.
- ECS tasks use public IPs for low-cost outbound access; security groups still deny direct inbound internet traffic.
- Add private subnets plus NAT or VPC endpoints before processing anything beyond synthetic demo data.

## Bedrock Gate

The minimum demo defaults to the `apac.amazon.nova-lite-v1:0` geographic inference profile through the Bedrock Converse API. Nova Lite is profile-only from Singapore, so inference can be routed among the profile's APAC destination Regions. This avoids the unrestricted global profile and third-party model first-use approval. Keep synthetic data until APAC processing is approved, and verify model availability, account entitlement, destinations, quotas, IAM scope, guardrail policy, latency, and cost immediately before deployment because the Bedrock catalog changes over time.

The AI ECS task role has `bedrock:InvokeModel` only for the selected APAC inference profile and its current destination foundation-model ARNs. Foundation-model access is conditioned on that profile. Reconcile the destination list against current AWS profile metadata before deployment because AWS can update profile destinations. The application uses the standard AWS credential chain and must not receive a long-lived Bedrock API key.

## GitHub And OIDC

Use exact OIDC subject claims for the main-branch publisher and protected `demo` environment deployer. Pass all three ECR repositories and ECS services to `github-actions-oidc.yaml`. The publisher can upload/scan only those repositories; the deployer can update only those services and pass only the named task roles.

The complete GitHub variable list and smoke-test secret are in `docs/cicd-pipeline.md`. Require environment reviewers, branch protection, secret scanning, push protection, CodeQL, dependency review, service integration, container builds, and AI evaluation checks before release.

## Go/No-Go

Do not deploy when any required variable is absent, a service lacks circuit-breaker rollback, an image has a Critical/High finding above policy, an AI/security evaluation fails, model residency is unresolved for the selected data class, or no previous stable task revision exists for rollback.
