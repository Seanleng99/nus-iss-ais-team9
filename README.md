# AI Financial Wellness Coach

Multi-agent financial education platform for young adults in Singapore. The system provides budgeting guidance, spending insights, goal planning, and investment education while avoiding regulated financial advice.

This repository is an executable synthetic-data demo. A LangGraph workflow uses Amazon Bedrock for model-driven routing, specialist interpretation, synthesis, and compliance review. Deterministic tools and hard guardrails remain grounding controls. The user workspace provides persisted profiles, transactions, monthly budgets, savings goals, dashboard summaries, and backend-built coaching snapshots. End-user identity, consent controls, and production RAG ingestion remain later gates. See `docs/requirements-traceability.md` before treating a scaffolded capability as complete.

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
- `docs/model-selection.md`: repeatable Bedrock candidate comparison and current model decision.
- `docs/rag-source-governance.md`: source approval, freshness, ingestion, withdrawal, and corpus traceability.
- `docs/operations.md`: SLO candidates, monitoring, alerts, load evidence, and incident response.
- `docs/operational-evidence.md`: retained CI, release, live-model, load, and AWS control evidence.
- `docs/cicd-pipeline.md`: GitHub/AWS pipeline and required configuration.

## Target Architecture

- Presentation tier: Streamlit deployed as an ECS Fargate service.
- Application tier: FastAPI backend for access control, profiles, transactions, monthly budgets, goals, dashboard summaries, and backend-built financial snapshots.
- AI tier: private FastAPI service with a model-driven LangGraph orchestrator and five agents.
- Data tier: PostgreSQL for transactional records and a vector database for controlled financial education content.
- AWS services: Bedrock, RDS PostgreSQL, ECR with Inspector scanning, Secrets Manager, ECS Fargate, and CloudWatch.

Streamlit calls the application backend from the server side, and the backend calls the private AI service. Separate service keys are injected from Secrets Manager and never sent to the browser. All three services can scale and roll back independently.

## Agents

- Spending Agent: spending summaries, patterns, and anomaly explanations.
- Budget Agent: rule-constrained monthly budget recommendations.
- Goal Strategy Agent: savings goal decomposition and progress adjustments.
- Investment Education Agent: reads the Education RAG collection to provide source-grounded education; not financial advice.
- Risk & Compliance Agent: reviews specialist evidence and applies independent policy validation; it does not query the Education RAG collection and uses a separate Policy RAG boundary.

Shared guardrails run before and after every agent call. The Risk & Compliance Agent is a final validation layer, not the only safety control.

## Local Development

```powershell
cd C:\ai-financial-wellness-coach
docker compose up --build
```

Open Streamlit at `http://localhost:8501`. Backend health is available at `http://localhost:8080/health`, and AI service health at `http://localhost:8001/health`.

The Streamlit workspace includes Overview, Transactions, Budget, Goals, Coach, and Profile pages. The sidebar profile ID is a synthetic demo identifier, not end-user authentication.

Compose runs `alembic upgrade head` as a one-shot task before starting the backend. When running the backend separately, start PostgreSQL and apply migrations first:

```powershell
cd C:\ai-financial-wellness-coach\apps\backend
alembic upgrade head
```

Compose explicitly uses `MODEL_PROVIDER=local_fixture` so local integration tests do not require AWS credentials or incur model charges. This fixture is deterministic and permitted only when `APP_ENV` is `local` or `test`; deployed environments fail configuration validation unless `MODEL_PROVIDER=bedrock`.

To run the services separately:

```powershell
cd C:\ai-financial-wellness-coach\apps\ai-service
pip install -e ".[dev]"
$env:MODEL_PROVIDER="local_fixture" # remove this to exercise Bedrock with an AWS identity
uvicorn app.main:app --reload --port 8001

cd C:\ai-financial-wellness-coach\apps\backend
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8080

cd C:\ai-financial-wellness-coach\apps\frontend
pip install -e ".[dev]"
streamlit run app.py --server.port 8501
```

## CI/CD And LLMSecOps

GitHub Actions detects affected services, runs their Python tests and security gates, and builds only their containers. Backend or AI changes also run the cross-service integration and load smoke tests. Docs-only pushes and pull requests do not start CI. Successful push CI for the current `main` SHA automatically starts `Release to AWS`, which publishes and deploys only changed service images. A separate weekly/manual workflow records privacy-safe live Bedrock/RAG, load, retention, scaling, and CloudWatch evidence. Setup requirements and private-repository plan limitations are documented in `docs/cicd-pipeline.md`.

## Evaluation

Run the release gate from the repository root after installing the AI service:

```powershell
python -m app.evals.gate --policy infra/llmsecops/evaluation-policy.json --output evaluation-results.json
```

Use only synthetic financial profiles in the current demo. The production-readiness exclusions and AWS go/no-go sequence are documented in `infra/aws/README.md`.

Evaluation policy v4 enforces every case conjunctively across routing, dynamic dependencies,
RAG, deterministic guardrails, regulated-advice behavior, and paired fairness consistency.
The weekly AWS workflow repeats the expanded live suite three times and blocks on any case,
latency, cost, or synthetic-cleanup failure.
