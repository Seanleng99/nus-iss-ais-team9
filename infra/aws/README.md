# AWS Demo Infrastructure

The repository includes a minimum-size, synthetic-data deployment for AWS account `902552928492` in `ap-southeast-1`:

- `demo-foundation.yaml` creates two public application subnets, two private database subnets, an internet-facing ALB behind a public HTTPS CloudFront distribution, CloudFront origin verification, an admin-created-user Cognito pool and public PKCE client, security groups, a minimum Single-AZ RDS PostgreSQL instance, three scan-on-push ECR repositories with ten-image retention, a Container-Insights-enabled ECS cluster, Cloud Map, generated service secrets, 30-day log groups, and separate application and AI task roles.
- `demo-application.yaml` creates three minimum-size Fargate services, backend/AI CPU target tracking from one to two tasks, private DNS, task definitions, target groups, header-gated ALB routing, an optional modern HTTPS origin listener, a CloudWatch dashboard, seven alarms, SNS alerts, and an ECS deployment-failure EventBridge rule.
- `github-actions-oidc.yaml` creates narrowly scoped image-publishing and ECS-deployment roles using GitHub OIDC. The deployment role can read the operational dashboard, alarms, confirmed subscription count, logs, and scaling configuration for evidence collection, plus audit only the exact Education and Policy Knowledge Bases and governed S3 prefixes.

The public-subnet task design avoids NAT Gateway cost. Tasks receive public IPs for outbound ECR, Secrets Manager, Cognito, and Bedrock access, but their security groups permit inbound traffic only from the ALB or the calling service. Bootstrap and edge hardening discover AWS's maintained CloudFront origin-facing prefix list, restrict ALB ingress to it, and require a generated `X-Coach-Origin-Verify` value before either listener forwards. The default CloudFront hostname still cannot select the target modern viewer TLS policy, and its origin remains HTTP until the guarded custom-domain path is activated. Use synthetic data only until the custom domain and both ACM certificates are supplied and validated.

RDS PostgreSQL is encrypted, has no public address, accepts port 5432 only from the backend security group, and uses an RDS-managed master secret. Investment Education and Risk and Compliance retrieve from separately provisioned Amazon Bedrock Knowledge Bases; CloudFormation scopes the AI task role to those exact resources.

## Automated Bootstrap

After GitHub and AWS browser authentication, start Docker Desktop and run the bootstrap with the
approved Education and Policy Knowledge Base IDs:

```powershell
.\infra\scripts\bootstrap_demo.ps1 `
  -EducationKnowledgeBaseId <10-character-education-kb-id> `
  -PolicyKnowledgeBaseId <10-character-policy-kb-id>
.\infra\scripts\configure_github.ps1
```

Add `-AlertEmail address@example.com` to the bootstrap command when email notifications are required, then confirm the AWS SNS subscription. Re-run both scripts after changing these templates so the AWS stacks and operational GitHub variables remain synchronized.

After confirmation, exercise the full CloudWatch-to-SNS path and retain privacy-safe evidence with `infra/scripts/test_operational_alert.ps1 -ExpectedEndpoint address@example.com -Confirmation TEST-OPERATIONAL-ALERT`. The operations owner must acknowledge receipt separately; successful AWS action history alone does not prove inbox delivery.

The first script validates the AWS account, discovers both data sources and governed S3 locations, deploys the foundation stack, builds and publishes bootstrap images, creates the ECS services with both corpus pins, and deploys the OIDC roles. The second configures GitHub Actions variables, including both collections' exact knowledge-base/data-source/bucket/prefix/corpus identifiers, the `demo` environment restricted to `main`, the smoke-test secret, and repository security settings. After the initial push and successful checks, run `protect_main.ps1`; it enables pull-request and CI requirements when the private-repository plan supports branch protection and otherwise reports the plan limitation.

For an existing demo stack that predates user authentication, first release the compatible images through the normal CI/CD path. Then activate Cognito, CloudFront, and ownership enforcement with the exact deployed 40-character release SHA:

```powershell
.\infra\scripts\activate_user_auth.ps1 `
  -ExpectedReleaseSha <released-main-commit-sha> `
  -DemoUserEmail user@example.com `
  -Confirmation ACTIVATE-OIDC
```

The script refuses to continue unless the stable deployed backend and frontend images use that SHA. It captures all three currently deployed immutable image URIs and passes them back to CloudFormation so older stack parameters cannot replace images deployed by the release workflow. It applies the nullable ownership migration before enabling OIDC, updates both stacks, removes the automation credential from the frontend task, optionally sends an admin-created Cognito invitation, and refreshes GitHub URLs. Existing unowned synthetic profiles remain accessible only to allowlisted automation identities and cannot be claimed by an authenticated user.

If a frontend-only corrective release follows the main authentication release, pass its SHA separately as `-ExpectedFrontendReleaseSha`; the backend remains pinned by `-ExpectedReleaseSha`.

## Deployment Order

1. Confirm the account, region, cost budget, and Bedrock model decision. The initial demo is synthetic-data only.
2. Authenticate with short-lived GitHub and AWS browser sessions.
3. Run `bootstrap_demo.ps1` and wait for all three ECS services to stabilize.
4. Run `configure_github.ps1`, commit, and push the repository to `main`.
5. Successful push CI for the current `main` SHA automatically starts `Release to AWS`.
6. For a pre-authentication stack, run `activate_user_auth.ps1` with that release SHA and invite a synthetic demo user. Fresh bootstrap deployments already include this boundary.
7. Verify Cognito login, same-owner access, cross-owner denial, unauthenticated denial, image scanning, deployment, prompt-injection blocking, and rollback.
8. Manually run `AWS Operational Validation`, retain its evidence artifact, and optionally enable the task-replacement exercise.
9. Run `protect_main.ps1` after the first successful workflow creates the required status-check contexts. Upgrade the GitHub plan if branch protection remains unavailable for the private repository.

## Edge Hardening

After a compatible release is stable, activate the CloudFront managed-prefix and origin-header restrictions without changing the public hostname:

```powershell
.\infra\scripts\harden_edge.ps1 `
  -ExpectedReleaseSha <released-main-commit-sha> `
  -Confirmation HARDEN-EDGE
```

The command pins all deployed images, updates CloudFront before making the ALB default action deny access, waits for the services, proves the CloudFront health path still works, and verifies that a headerless direct-origin request is denied at the network layer or with HTTP 403.

To complete custom-domain TLS, first create or import an issued ACM certificate in `us-east-1` for the viewer name and an issued certificate in the deployment Region for the origin name. Both names must be in the supplied public Route 53 hosted zone. Then run:

```powershell
.\infra\scripts\harden_edge.ps1 `
  -ExpectedReleaseSha <released-main-commit-sha> `
  -CustomDomainName coach.example.com `
  -CustomDomainHostedZoneId Z1234567890ABC `
  -CloudFrontViewerCertificateArn <us-east-1-certificate-arn> `
  -OriginDomainName origin.coach.example.com `
  -OriginCertificateArn <regional-certificate-arn> `
  -Confirmation HARDEN-EDGE
```

The script rejects incomplete inputs, private hosted zones, certificates that are not issued, certificates that do not cover their assigned names, and images that do not match the expected release. It creates the HTTPS ALB listener before switching CloudFront to the custom origin, retains the default CloudFront callback temporarily for safe transition, updates Cognito and application URLs, refreshes GitHub variables, and runs the edge security probe. Certificate issuance and DNS ownership are operator prerequisites; the script does not request certificates or bypass domain validation.

## Task Configuration Matrix

| Task | Plain environment | Secrets | Task-role access |
|---|---|---|---|
| Frontend | `APP_ENV=demo`, `BACKEND_BASE_URL`, auth-required flag, Cognito client/metadata/redirect settings | OIDC cookie secret | None |
| Backend | `APP_ENV=demo`, `AI_SERVICE_BASE_URL`, timeout, database host/name/port, TLS mode, 30-day trace retention, strict Cognito issuer/JWKS/client/token-use settings, automation user-ID prefixes | Automation-only `BACKEND_API_KEY`, `AI_SERVICE_API_KEY`, RDS username/password | None |
| AI service | `APP_ENV=demo`, `MODEL_PROVIDER=bedrock`, both RAG providers, model ID, Education and Policy Knowledge Base IDs, exact corpus versions, retrieval thresholds, temperatures, prompt version | `AI_SERVICE_API_KEY` | Approved Bedrock profile, destination models, and read-only retrieval from both exact Knowledge Bases |

Do not inject either service API key into authenticated Streamlit. Do not place runtime AWS credentials in GitHub or application secrets. ECS tasks obtain AWS permissions from task roles. The frontend writes its Streamlit OIDC configuration from environment/Secrets Manager at process startup with owner-only file permissions; tokens and the cookie secret must never enter logs or traces.

## Network Rules

- Internet to CloudFront: HTTPS, with HTTP redirected to HTTPS. Custom-domain activation uses an ACM certificate from `us-east-1`, SNI, and `TLSv1.2_2021`; the default hostname remains a synthetic-demo fallback.
- CloudFront to ALB: the default-hostname stage uses HTTP plus a generated origin-verification header. Custom-domain activation uses HTTPS with TLS 1.2 or later and a regional ACM certificate whose name matches the origin DNS record.
- Direct internet to demo ALB: the security group admits only the AWS-managed CloudFront origin-facing prefix list after activation. One weighted prefix-list rule covers the staged listener range to remain within the default security-group quota; the ALB has listeners only on ports 80 and 443. Both listeners return HTTP 403 unless CloudFront supplies the generated verification header.
- ALB to frontend/backend target security groups: only their container ports.
- Backend to AI: TCP 8001 only.
- Backend to private RDS PostgreSQL: TCP 5432 only.
- ECS tasks use public IPs for low-cost outbound access; security groups still deny direct inbound internet traffic.
- Move application tasks to private subnets plus NAT or VPC endpoints before processing anything beyond synthetic demo data. RDS already uses private database subnets.

## Database Migrations

The backend image contains Alembic and the versioned migration history. Bootstrap runs `alembic upgrade head` once after the ECS application stack is created. Every automatic backend release runs the one-shot ECS migration task, even when no migration path was detected, and checks its exit code before updating the backend service. This makes migration state a deployment invariant and protects against path-classification drift.

The authentication activation script also runs migration `20260829_0007` before changing task authentication settings. Its released-image SHA check prevents an old task definition from reporting success at an older Alembic head. It now discovers the CloudFront origin-facing prefix list and supplies the generated origin-verification secret to the application stack. The frontend reads OIDC discovery through the public backend metadata adapter. That adapter verifies the configured Cognito issuer and JWKS URL, preserves Cognito's discovery document, and adds the allowed `logout_uri` required by Cognito's managed logout endpoint; it never receives browser tokens or cookies.

Application releases build, scan, and update only services selected by the CI change manifest. Unchanged ECS task definitions remain active. If post-deployment checks fail, explicit rollback restores only services whose new task definitions were successfully deployed; ECS circuit-breaker rollback remains responsible for an individual service update that fails before completion.

Schema changes must remain compatible with the currently running backend during deployment. Service rollback does not automatically reverse a successful database migration; use expand-and-contract changes and create an explicit corrective migration when needed.

## Bedrock Gate

The minimum demo defaults to the `apac.amazon.nova-lite-v1:0` geographic inference profile through the Bedrock Converse API. Nova Lite is profile-only from Singapore, so inference can be routed among the profile's APAC destination Regions. This avoids the unrestricted global profile and third-party model first-use approval. Keep synthetic data until APAC processing is approved, and verify model availability, account entitlement, destinations, quotas, IAM scope, guardrail policy, latency, and cost immediately before deployment because the Bedrock catalog changes over time.

The AI ECS task role has `bedrock:InvokeModel` only for the selected APAC inference profile and its current destination foundation-model ARNs. Foundation-model access is conditioned on that profile. Reconcile the destination list against current AWS profile metadata before deployment because AWS can update profile destinations. The application uses the standard AWS credential chain and must not receive a long-lived Bedrock API key.

## GitHub And OIDC

Use exact OIDC subject claims for the main-branch publisher and `demo` environment deployer. Pass all three ECR repositories and ECS services to `github-actions-oidc.yaml`. The publisher can upload/scan only those repositories; the deployer can update only those services and pass only the named task roles.

The complete GitHub variable list and smoke-test secret are in `docs/cicd-pipeline.md`. Successful push CI for the current `main` SHA automatically starts the release workflow. The weekly operational, Education governance, and Policy governance workflows use the same short-lived demo-environment OIDC role and produce 90-day privacy-safe evidence. Governance workflows have only read access to their exact collections; corpus mutation remains a reviewed operator action using `infra/scripts/rag_source_governance.py`. Native required environment reviewers, branch protection, and GitHub Code Security are unavailable for this private repository on the current GitHub plan; enable them after a plan upgrade. Bandit remains the active Python SAST gate. Secret scanning and push protection are also configured only when the plan supports them.

## Go/No-Go

Do not deploy when any required variable is absent, a database migration fails, a service lacks circuit-breaker rollback, an image has a Critical/High finding above policy, an AI/security evaluation fails, model residency is unresolved for the selected data class, or no previous stable task revision exists for rollback. Do not claim authentication evidence until a Cognito user completes login and automated checks demonstrate unauthenticated rejection plus cross-owner isolation. Do not claim operational readiness until the origin restriction is live, custom-domain TLS is activated, an SNS notification path is tested, and a successful AWS operational-evidence artifact is retained.
