# AI Financial Wellness Coach

Multi-agent financial education platform for young adults in Singapore. The system provides budgeting guidance, spending insights, goal planning, and investment education while avoiding regulated financial advice.

This repository is an executable synthetic-data demo. A LangGraph workflow uses OpenAI GPT-6 Luna for model-driven routing, specialist interpretation, synthesis, and compliance review. Deterministic tools and hard guardrails remain grounding controls. The user workspace provides persisted profiles, transactions, monthly budgets, savings goals, dashboard summaries, and backend-built coaching snapshots. Cognito OIDC authentication, immutable profile ownership, CloudFront custom-domain TLS, HTTPS origin restriction, and live cross-owner isolation evidence are implemented for the AWS demo. This does not approve real personal financial data or production users.

## Repository Layout

```text
apps/
  frontend/          Streamlit user interface
  backend/           FastAPI application API, persistence, and Alembic migrations
  ai-service/        Private FastAPI agent orchestration, guardrails, RAG hooks, and evals
docs/                Architecture, security, evaluation, and deployment documentation
infra/               Docker, AWS OIDC, deployment scripts, and LLMSecOps policy
```

## Design Evidence

- `docs/requirements-traceability.md`: requirement-to-evidence status and remaining work.
- `docs/architecture.md`: logical and physical architecture, trust boundaries, and ECS/EKS decision.
- `docs/agent-design.md`: roles, model strategy, memory, tools, prompts, MCP, and A2A.
- `docs/responsible-ai.md`: intended use, fairness, accountability, human control, and lifecycle gates.
- `docs/security-risk-register.md`: AI/security risks, controls, residual ratings, and owners.
- `docs/evaluation-plan.md`: datasets, expected outputs, metrics, drift, and acceptance criteria.
- `docs/model-selection.md`: current OpenAI model decision and historical Bedrock comparison.
- `docs/representative-user-validation.md`: representative-user protocol for explanations, confidence, uncertainty, sources, and safe next actions.
- `docs/data-lifecycle.md`: versioned retention, consent, export, deletion, and scheduled-purge controls.
- `docs/rag-source-governance.md`: source approval, freshness, ingestion, withdrawal, and corpus traceability.
- `docs/policy-rag-governance.md`: separate policy-corpus lifecycle, runtime enforcement, and deployment gates.
- `docs/operations.md`: SLO candidates, monitoring, alerts, load evidence, and incident response.
- [Investment Agent 调用链日志](docs/investment-call-logging.md): login, method calls, RAG/model execution, response packaging, CloudWatch queries, and explicitly marked synthetic Q&A logs.
- `docs/operational-evidence.md`: retained CI, release, live-model, load, and AWS control evidence.
- `docs/cicd-pipeline.md`: GitHub/AWS pipeline and required configuration.
- `docs/container-security.md`: exact-version image-scan exceptions, current risk review, and expiry controls.
- `docs/final-assessment.md`: assessor-facing scope, architecture, interaction, evidence baseline, and acceptance gate.
- `docs/demo-runbook.md`: reproducible six-scenario final demonstration procedure.

## Target Architecture

- Presentation tier: Streamlit deployed as an ECS Fargate service.
- Application tier: FastAPI backend for access control, profiles, transactions, monthly budgets, goals, dashboard summaries, and backend-built financial snapshots.
- AI tier: private FastAPI service with a model-driven LangGraph orchestrator and five agents.
- Data tier: PostgreSQL for transactional records and packaged, governed Education and Policy corpora.
- AWS services: Cognito, CloudFront, RDS PostgreSQL, ECR with Inspector scanning, Secrets Manager, ECS Fargate, and CloudWatch; the AI service calls the OpenAI API.

After authentication activation, Streamlit completes Cognito authorization-code login with PKCE and sends the server-side ID token to the backend. The backend validates the JWT and authorizes each profile by immutable issuer and subject. A separately scoped automation key remains only for synthetic CI/operational users, and the backend-to-AI key remains an independent service secret. All three services can scale and roll back independently.

## Budget planning and confirmation

In Coach, ask for category limits such as: "Set my October 2026 budget to SGD 500 for food and SGD 120 for pet care." Coach collects missing month/year, category, amount, and currency details, then previews the exact changes. Reply `confirm budget` to save, `cancel` to discard, or provide corrections. Income is not required to record an explicit category limit. Currency and dates are never defaulted from the current month or a dollar symbol.

Drafts belong to the authenticated profile and conversation. Confirmation updates only the listed categories and preserves other limits. A changed budget, an intervening turn, or a preview older than 30 minutes requires a fresh preview and confirmation. Draft consumption, budget updates, and the chat exchange commit together. The Budget page provides allocation and spending charts, over-limit indicators, and suggested or custom category names; transactions also accept custom categories so their spending can be tracked against the same limits.

Apply migration `20260928_0010` with `alembic upgrade head` before running the updated backend (Compose already runs migrations). The offline model fixture accepts explicit `category: amount` syntax, for example: "Set budget for October 2026 in SGD; food: 500, pet care: 120". Production model extraction supports natural-language requests. Coach currently saves monthly SGD budgets; ambiguous dates, other currencies, and non-monthly periods require clarification.

Coach now supports a first-stage **category budget planner**: ask “Help me create a realistic monthly budget,” provide take-home income and a savings allocation, and supply category limits or request recorded-spending suggestions. Coach clarifies missing details, asks whether all commitments are included, and checks the complete plan for funding gaps before confirmation. Savings stay separate from expense limits and appear in Budget and Overview after saving. See [Budget planning](docs/budget-planning.md) for the workflow, contracts, migration `20260929_0011`, examples, tests, and deferred features.

## Agents

- Spending Agent: spending summaries, patterns, and anomaly explanations.
- Budget Agent: illustrative monthly budget calculations and category-limit drafts that require user confirmation before persistence.
- Goal Strategy Agent: savings goal decomposition and progress adjustments.
- Investment Education Agent: reads Education RAG first, supplements missing stable concepts with clearly labeled model knowledge, then passes the combined answer through independent safety review; not financial advice.
- Risk & Compliance Agent: reviews specialist evidence and applies independent policy validation; it does not query the Education RAG collection and uses a separate Policy RAG boundary.

Shared guardrails run before and after every agent call. The Risk & Compliance Agent is a final validation layer, not the only safety control.

## Local Development

```powershell
cd C:\ai-financial-wellness-coach
docker compose up --build
```

Open Streamlit at `http://localhost:8501`. Backend health is available at `http://localhost:8080/health`, and AI service health at `http://localhost:8001/health`.

The Streamlit workspace includes Overview, Transactions, Budget, Goals, Coach, and Profile pages. Local Compose leaves authentication disabled for fixture-based development. The AWS activation procedure enables Cognito sign-in and owner-isolates every profile-scoped route.

Compose runs `alembic upgrade head` as a one-shot task before starting the backend. When running the backend separately, start PostgreSQL and apply migrations first:

```powershell
cd C:\ai-financial-wellness-coach\apps\backend
alembic upgrade head
```

Compose explicitly uses `MODEL_PROVIDER=local_fixture` so local integration tests do not need an OpenAI API key or incur model charges. This fixture is deterministic and permitted only when `APP_ENV` is `local` or `test`; deployed environments fail configuration validation unless `MODEL_PROVIDER=openai` with both governed local-document retrievers.

To run the services separately:

```powershell
cd C:\ai-financial-wellness-coach\apps\ai-service
pip install -e ".[dev]"
$env:MODEL_PROVIDER="local_fixture" # use openai plus OPENAI_API_KEY for a live synthetic test
uvicorn app.main:app --reload --port 8001

cd C:\ai-financial-wellness-coach\apps\backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8080

cd C:\ai-financial-wellness-coach\apps\frontend
pip install -e ".[dev]"
streamlit run app.py --server.port 8501
```

## CI/CD And LLMSecOps

GitHub Actions detects affected services, runs their Python tests and security gates, and builds only their containers. Backend or AI changes also run the cross-service integration and load smoke tests. Docs-only pushes and pull requests do not start CI. Successful push CI for the current `main` SHA automatically starts `Release to AWS`. An application release publishes and deploys all three service images from that SHA, including the backend migration check: after a failed release rolls back, a later push diff alone cannot identify earlier fixes still missing from AWS. A separate weekly/manual workflow records privacy-safe live OpenAI/RAG, governed data-lifecycle retention, load, scaling, and CloudWatch evidence. Setup requirements and private-repository plan limitations are documented in `docs/cicd-pipeline.md`.

## Evaluation

Run the release gate from the repository root after installing the AI service:

```powershell
python -m app.evals.gate --policy infra/llmsecops/evaluation-policy.json --output evaluation-results.json
```

Use only synthetic financial profiles in the current demo. The production-readiness exclusions and AWS go/no-go sequence are documented in `infra/aws/README.md`.

Evaluation policy v7 enforces all 80 cases/pairs conjunctively across routing, dynamic agent/tool
dependencies, direct and conditional Education RAG, Policy RAG, deterministic guardrails,
regulated-advice behavior, and paired fairness consistency.
The weekly AWS workflow repeats the expanded live suite three times and blocks on any case,
latency, cost, or synthetic-cleanup failure.

Full-document local retrieval and its separate 99% evidence-quality gate are documented in [RAG quality acceptance](docs/rag-quality.md). This score does not establish real-model answer quality.
