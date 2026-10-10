# CI/CD Pipeline

## Current delivery path

A push to `main` runs CI and starts `Release to AWS` only after CI succeeds for the current commit. Application releases build and scan all three service images from that tested SHA so recovery also includes earlier fixes. The backend deployment runs Alembic before the service update. Post-deployment smoke requires successful live model execution for all five agents and verifies unauthenticated denial, scoped automation access, Education citations, independent Policy evidence, corpus pins, and persisted trace provenance. Failed checks restore the task definitions that were updated during the release; ECS deployment circuit breakers cover failed service starts.

Every deployment runs the following required probes through the deployed coaching API:

| Agent | Required live smoke case |
| --- | --- |
| Budget | SGD 4,000 income minus SGD 1,500 recurring expense gives SGD 2,500 disposable income |
| Spending | Two temporary stored current-month SGD records retain food 120, transport 30 and a count of two |
| Goal Strategy | An illustrative SGD 6,000 target over 12 months requires SGD 500 per month |
| Investment Education | Approved diversification explanation with governed Education citations |
| Risk & Compliance | Independent approval of the Education answer with governed Policy evidence |

Each role must have at least one completed, nonempty model call without an error
in both the response audit and its owner-scoped persisted trace. The checks also
require the expected model provider, current prompt version and reviewed role
reasoning/output limits. Router, capture and dependency-planner calls do not
substitute for specialist calls; capture drafts, missing results and clarification
responses fail the normal analysis probes. Budget, Spending and Goal use fresh
synthetic users and sessions. Investment Education and Risk & Compliance share
one successful Education probe, which verifies both model roles. CI runs the same
smoke entry point against local fixture services; the AWS release explicitly
requires the OpenAI provider.

The Spending probe seeds its synthetic profile and ledger through the owned
backend API, since backend aggregates take precedence over caller snapshots.
It deletes that user's workspace after trace verification, including when
seeding, model execution or verification fails.

Documentation and service README edits do not select deployment on their own. Every push still runs change detection, so a documentation-only successor cannot strand pending application changes. Governed RAG Markdown and runtime prompt files remain deployable inputs.

Main pushes classify all changes since the last successful `Deploy demo environment`
job, rather than just the newest push. Failed CI or deployment leaves application
changes pending; a successful release with a skipped deployment does not advance
the baseline. This lets a later security or pipeline fix release the pending
application changes. If no deployment is retained or its commit is outside the
checkout history, CI runs every service check. Pull requests retain their normal
base-to-head comparison. The change-manifest artifact also records the deployment
baseline used for classification.

The AI task check requires `MODEL_PROVIDER=openai`, `MODEL_ID=gpt-6-luna`, medium default reasoning with the reviewed role overrides, the [packaged current prompt identity](current-prompt-contract.md), both RAG providers set to `bedrock`, exact KB IDs and corpus pins, and an ECS `OPENAI_API_KEY` secret reference. Release ingests and audits both approved corpora before rendering the AI task. The key is stored in AWS Secrets Manager and is never a GitHub variable or repository secret.

Release rendering also replaces inherited timeout settings: model reads are bounded
at 30 seconds, specialist execution at 45 seconds, the whole AI workflow at 85
seconds, and backend AI transport at 90 seconds. Both rendered task definitions
are checked before deployment. The foundation sets the ALB idle timeout and
CloudFront origin response timeout to 120 seconds; the smoke client also waits
up to 120 seconds. This keeps the outer connections open long enough for the
bounded workflow to return. Existing environments need the gateway settings
updated when adopting these limits; an image update alone does not change them.
CloudFront's supported range is documented in the [AWS quotas](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cloudfront-limits.html).

The conditional Education smoke asks Budget to explain education relevant to its
own budget calculation. An independent education clause belongs to an Investment
specialist and does not demonstrate a Budget dependency. The smoke still requires
Budget as the sole selected specialist, a resolved Education tool dependency,
approved sources, grounded evidence and persisted retrieval provenance.

## Validation workflows

The integration load smoke uses one automation credential, so all its synthetic
profiles share the coaching quota. Its 20 requests run with concurrency two to
match the default per-principal limit. Every request must still return HTTP 200;
quota denials remain failures and the report records their HTTP status. Backend
quota tests separately verify rejection and `Retry-After` above the limit.

`AWS Operational Validation` runs weekly or on demand against the deployed synthetic demo. It repeats the live OpenAI/RAG cases, measures bounded load and estimated model cost, checks service state, lifecycle controls, dashboard and alarms, and can exercise backend task replacement. Its current model expectation is GPT-6 Luna. This is the required live acceptance evidence for the migration; historical Nova results cannot validate it.

`RAG Source Governance` validates both approved local corpora and audits the deployed KBs/S3 objects weekly or on demand. Its dedicated OIDC role has read-only corpus and KB permissions. It checks approval, provenance, review deadlines, content inspection, SHA-256 checksums, sidecars and completed ingestion, and retains privacy-safe evidence for 90 days. Historical Bedrock generation comparisons remain historical.

One [ci.yml](../.github/workflows/ci.yml) defines service tests, seven owned
agent/RAG offline suites, required metrics, Promptfoo security scans, infrastructure
checks and optional live evaluations. No reusable test workflow is called.
Infrastructure/helper tests have one owner; agent selections exclude their files
from the remaining AI suite. The required Agent gate and offline OWASP scan still
block releases. See [all jobs and test ownership](agent-test-workflows.md) and
[security coverage](project-security-scan.md).

The frontend test job installs only the frontend and shared packages. The shared
package declares Pydantic as a runtime dependency because trace sanitization uses
the shared calendar-scope models. A frontend regression renders routing decisions
with budget and spending scopes, including nested before/after values, so a missing
dependency fails CI instead of first failing in the deployed Decision traces page.

The `Dependency review` job audits each service's resolved Python dependencies
with pinned `pip-audit` and fails on any known advisory. After the audit,
`infra/scripts/summarize_dependency_audit.py` writes a report to the run's job
summary and to the `dependency-audit-summary.md` artifact, even when the audit
fails. The report gives per-service totals, a package-health chart, and tables of
vulnerabilities and skipped packages. `pip-audit` provides advisory identifiers
and fix versions, not severity scores, so the chart groups packages as clean,
vulnerable with a fix, vulnerable without a fix, or skipped. Each repeated advisory
for one package counts once. A missing or malformed service result appears as an
unavailable audit and fails the report step. The report does not change the
audit's pass/fail result.

CI tools that can fail a build use exact versions: Ruff, `pip-audit`, Bandit,
and the npm, Promptfoo and Playwright versions used by the security scan.
Dependabot proposes weekly updates for GitHub Actions, the three Python services
and `security/promptfoo`. Each update arrives as a pull request that must pass CI
before merging, so pinned tool upgrades are reviewed instead of arriving with
a new upstream release.

`CI and LLMSecOps` offers a default-off Yes/No checkbox for seven advisory deployed-model/AWS evaluations followed by the bounded live security scan. It replaces the separate Budget and one-time Investment live workflow definitions. These optional failures cannot block CI or release; existing mandatory release smoke checks remain required. `Final Assessment` remains a manual academic evidence inventory that requires successful main CI and calls `AWS Operational Validation`; it is not part of every release.

## Workflow inventory

The workflow audit keeps the following responsibilities:

| Workflow | Purpose and trigger |
| --- | --- |
| CI and LLMSecOps | All service, agent/RAG and security jobs; PR/main/weekly checks and manual optional live evaluations |
| Release to AWS | Deployment after successful push CI at the current main SHA |
| RAG Source Governance | Weekly/manual freshness and integrity checks for both packaged corpora |
| AWS Operational Validation | Weekly/manual deployed-model, lifecycle, load and operational evidence |
| Model Drift Monitoring | Opt-in weekly/manual rubric-scored live capture and human-calibrated baseline comparison; current policy uses GPT-6 Luna for generation and grading, with GitHub reports and optional SNS alerts/input checks |
| Final Assessment | Manual academic evidence inventory and operational validation wrapper |
| Dependabot Updates | GitHub-managed dependency maintenance |

The duplicate **Policy RAG Source Governance** and notice-only **Historical
Bedrock Model Comparison** definitions have been removed. Historical reports
remain available; the assessment manifest now references current prompt/model
policy evidence and the combined governance workflow.

## GitHub configuration

`infra/scripts/configure_github.ps1` populates the OIDC role ARNs, ECS cluster/service/task names, ECR repositories, public health and coach URLs, corpus versions, dashboard and alarm identifiers, and bounded validation thresholds. It also sets `SMOKE_BACKEND_API_KEY` in the `demo` environment. The workflow assumes short-lived GitHub OIDC credentials; it does not store AWS access keys.

The OIDC deployment role has scoped Bedrock and S3 permissions for the two approved corpora: it can inspect and retrieve from the configured Education and Policy knowledge bases, read/list only their governed S3 prefixes, and start ingestion or publish objects within those prefixes. The separate RAG governance role is read-only for corpus and knowledge-base access. The deployment policy permits task/service inspection and task-definition registration, updates the three configured ECS services, and limits `iam:PassRole` to the configured ECS roles. Keep the `demo` environment restricted to `main`. Branch protection and native required reviewers depend on the repository plan.

Main pushes build images once in Release; PR/manual/scheduled CI retains build validation. A release superseded during image building skips all deployment steps and records the reason. Deployment-baseline selection requires actual successful service-update and safety-smoke steps, so a green superseded run cannot hide pending code.

## Change and acceptance gates

Model, prompt, retrieval, policy, tool, and capability changes require code review and evaluation evidence. The current choice of GPT-6 Luna is documented in [model selection](model-selection.md). Before claiming deployment acceptance, run the repeated synthetic evaluation and check routing, dynamic dependencies, safety, groundedness, citation/provenance, Chinese-language behavior, P95 latency, and actual estimated token cost against the policy thresholds. The direct OpenAI API does not provide Singapore regional processing through its Singapore storage-residency option, so this deployment remains synthetic-data only.
