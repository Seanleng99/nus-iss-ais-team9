# AI Financial Wellness Coach

Multi-agent financial education platform for young adults in Singapore. The system provides budgeting guidance, spending insights, goal planning, and investment education while avoiding regulated financial advice.

This repository is an executable synthetic-data demo. A LangGraph workflow uses OpenAI GPT-6 Luna for model-driven routing, specialist interpretation, synthesis, and compliance review. Deterministic tools and hard guardrails remain grounding controls. The user workspace provides persisted profiles, transactions, monthly budgets, savings goals, dashboard summaries, and backend-built coaching snapshots. Cognito OIDC authentication, immutable profile ownership, CloudFront custom-domain TLS, HTTPS origin restriction, and live cross-owner isolation evidence are implemented for the AWS demo. This does not approve real personal financial data or production users.

Application currency is fixed to **SGD**. Profile income, transaction amounts, goal amounts, budgets and cash-flow settings default missing or null currency to SGD and reject explicit other currencies at the API boundary. Forms use SGD and the sidebar shows the fixed currency. Dashboard totals include SGD records only. Historical records retain their original labels in API responses and exports; they are not converted or relabelled.

## Repository Layout

Coach's everyday Budget reasoning uses saved category limits and commitments together with spending evidence for the requested month or range. Prior history stays separate from the requested totals. General budgeting explanations do not require personal income; personal capacity estimates require income and explicit recurring schedules when no confirmed plan exists. See [Budget reasoning contracts](docs/budget-planning.md#everyday-reasoning-context) for the local implementation and verification limits.

```text
apps/
  frontend/          Streamlit user interface
  backend/           FastAPI application API, persistence, and Alembic migrations
  ai-service/        Private FastAPI agent orchestration, guardrails, RAG, and evals
  shared/            Shared financial math, language, and trace contracts
knowledge/           Approved Education/Policy documents and source manifests
security/            Security evaluation datasets and bounded scan harnesses
docs/                Architecture, security, evaluation, and deployment documentation
infra/               Docker, AWS OIDC, deployment scripts, and LLMSecOps policy
```

## Design Evidence

- [Documentation alignment audit](docs/documentation-audit-2026-10-10.md): review of all 100 tracked Markdown files against the current code, with per-file coverage and verification limits.
- [requirements-traceability](docs/requirements-traceability.md): requirement-to-evidence status and remaining work.
- [architecture](docs/architecture.md): logical and physical architecture, trust boundaries, and ECS/EKS decision.
- [agent-design](docs/agent-design.md): roles, model strategy, memory, tools, prompts, MCP, and A2A.
- [responsible-ai](docs/responsible-ai.md): intended use, fairness, accountability, human control, and lifecycle gates.
- [fairness testing](docs/fairness-testing.md): runtime demographic-assumption review, independent paired correctness, required live release testing, and evidence limits.
- [security-risk-register](docs/security-risk-register.md): AI/security risks, controls, residual ratings, and owners.
- [evaluation-plan](docs/evaluation-plan.md): datasets, expected outputs, metrics, drift, and acceptance criteria.
- [test organization](docs/test-organization.md): explicit agent/platform/shared ownership, CI gates and evidence artifacts.
- [Model drift monitoring](docs/model-drift-monitoring.md): same-model quality scoring with human-calibrated baselines, aggregate input comparisons, scheduled reporting, and activation requirements.
- [model-selection](docs/model-selection.md): current OpenAI model decision and historical Bedrock comparison.
- [representative-user-validation](docs/representative-user-validation.md): representative-user protocol for explanations, confidence, uncertainty, sources, and safe next actions.
- [data-lifecycle](docs/data-lifecycle.md): versioned retention, consent, export, deletion, and scheduled-purge controls.
- [rag-source-governance](docs/rag-source-governance.md): source approval, freshness, ingestion, withdrawal, and corpus traceability.
- [policy-rag-governance](docs/policy-rag-governance.md): separate policy-corpus lifecycle, runtime enforcement, and deployment gates.
- [operations](docs/operations.md): SLO candidates, monitoring, alerts, load evidence, and incident response.
- [Investment Agent call-chain logging](docs/investment-call-logging.md): login, method calls, RAG/model execution, response packaging, CloudWatch queries, and explicitly marked synthetic Q&A logs.
- [Chinese language support](docs/language-support.md): shared locale selection, fixed-message catalogs, supported scope, and the project-wide character inventory.
- [operational-evidence](docs/operational-evidence.md): retained CI, release, live-model, load, and AWS control evidence.
- [cicd-pipeline](docs/cicd-pipeline.md): GitHub/AWS pipeline and required configuration.
- [container-security](docs/container-security.md): exact-version image-scan exceptions, current risk review, and expiry controls.
- [final-assessment](docs/final-assessment.md): assessor-facing scope, architecture, interaction, evidence baseline, and acceptance gate.
- [demo-runbook](docs/demo-runbook.md): reproducible six-scenario final demonstration procedure.

## Target Architecture

- Presentation tier: Streamlit deployed as an ECS Fargate service.
- Application tier: FastAPI backend for access control, profiles, transactions, monthly budgets, goals, dashboard summaries, and backend-built financial snapshots.
- AI tier: private FastAPI service with a model-driven LangGraph orchestrator and five agents.
- Data tier: PostgreSQL for transactional records and separate Bedrock Knowledge Bases for governed Education and Policy retrieval; reviewed source documents and manifests are retained in Git and the AI image.
- AWS services: Cognito, CloudFront, RDS PostgreSQL, ECR with Inspector scanning, Secrets Manager, ECS Fargate, CloudWatch, and Bedrock Knowledge Bases backed by S3/S3 Vectors; the AI service calls the OpenAI API for generation.

After authentication activation, Streamlit completes Cognito authorization-code login with PKCE and sends the server-side ID token to the backend. The backend validates the JWT and authorizes each profile by immutable issuer and subject. A separately scoped automation key remains only for synthetic CI/operational users, and the backend-to-AI key remains an independent service secret. All three services can scale and roll back independently.

## Spending capture and the transaction ledger

In Coach, record spending in one natural sentence: "lunch 5.50", "dinner at jumbo seafood $120", or "can you help me add my Spotify monthly subscription that costs 10.90". Capture extracts the amount, description, and an optional inline date ("yesterday", "21/9", "last Saturday"), classifies a category, and saves the transaction to the authenticated profile only after the date is known. Polite directives ("please log…", "can you help me add…") and filler words are stripped from the description. Recurring wording flags an expense for the recurring summary, which reports the latest recorded amount for each item. The ledger can store explicit recurrence frequency, interval, dates and month-end terms. Scheduled captures require a preview and confirmation; a recurring flag without those terms cannot establish a monthly or upcoming total. Personal amounts use SGD by default; explicit foreign currencies are rejected. Amounts are never defaulted and future dates are rejected unless the wording indicates a booking.

Incomplete statements enter a short clarification flow instead of guessing. Missing amount or date triggers a follow-up question; reply with the value ("10.90", "today"), provide a correction to replace the draft, or `cancel` to discard it. A just-saved transaction can also be corrected in chat: "oh sorry its 18.90" (or a date such as "oh sorry it was yesterday") updates that record for the same profile within a short window, re-checks the budget limit, and replies with the new amount. To edit an earlier record by name, say "change my Anniversary Dinner spending to 988" (or "would you be able to edit the spending to 988" after naming the transaction); Coach finds the match in your own records, previews the exact change, and applies it only after you reply `confirm` — you can narrow by date ("change my Lunch on 1st October to 25"), ambiguous matches list the candidates and ask you to pick one by description or date, and `cancel` changes nothing. Deleting works the same way: "delete my Anniversary Dinner transaction" previews the exact record and only removes it after you reply `confirm`. Pending drafts belong to the authenticated profile and conversation and expire after a TTL. Batch entry is supported: multi-line lists, "and"-joined items, and multiple sentences each become separate dated drafts, with undated lines asked one at a time. A saved capture also reports whether it pushed its category over the monthly budget limit. The Transactions page lists, edits, and deletes recorded transactions, including custom categories shared with Budget limits.

## Budget planning and confirmation

In Coach, ask for category limits such as: "Set my October 2026 budget to 500 for food and 120 for pet care." Coach collects missing month/year, category and amount details, then previews the exact changes. All personal financial amounts use SGD, including bare numbers and `$`; Coach and agents do not ask for currency confirmation. Explicit foreign-currency amounts are unsupported and require SGD amounts without automatic conversion. Reply `confirm budget` to save, `cancel` to discard, or provide corrections. Income is not required to record an explicit category limit. The sidebar month is a default when no period is specified; explicit months, ranges and years override it. Ambiguous dates still require clarification.

Coach can show all saved budgets, compare saved months, summarise a year, change limits across multiple saved months, remove category limits and delete specified monthly budgets. Examples: "Show all my saved budgets", "Compare my budgets from August through October 2026", "Change food to SGD 600 in my budgets from October through December 2026", "Remove the food limit from my November 2026 budget", and "Delete my November 2026 budget". Reads and comparisons make no changes. Edits and deletions preview every affected month and require `confirm budget`; batch changes apply together or remain unapplied. Unspecified values and financial records are kept. See [budget scope and management](docs/budget-planning.md#saved-budgets-across-months-and-years) for safeguards, APIs and capacity semantics.

Drafts belong to the authenticated profile and conversation. Confirmation updates only the listed categories and preserves other limits. A changed budget, an intervening turn, or a preview older than 30 minutes requires a fresh preview and confirmation. Draft consumption, budget updates, and the chat exchange commit together. The Budget page provides allocation and spending charts, over-limit indicators, and suggested or custom category names; transactions also accept custom categories so their spending can be tracked against the same limits.

Apply all checked-in migrations with `alembic upgrade head` before running the updated backend (`20261010_0018` is the current head) (Compose already runs migrations). The offline model fixture accepts explicit `category: amount` syntax, for example: "Set budget for October 2026 in SGD; food: 500, pet care: 120". Production model extraction supports natural-language requests. Coach currently saves monthly SGD budgets; ambiguous dates, other currencies, and non-monthly periods require clarification.

Coach now supports a first-stage **category budget planner**: ask “Help me create a realistic monthly budget,” provide take-home income and a savings allocation, and supply category limits or request recorded-spending suggestions. Coach clarifies missing details, asks whether all commitments are included, and checks the complete plan for funding gaps before confirmation. Savings stay separate from expense limits and appear in Budget and Overview after saving. See [Budget planning](docs/budget-planning.md) for the workflow, contracts, migration `20260929_0011`, examples, tests, and deferred features.

Stage two adds selectable flexible, 50/30/20, 80/20, zero-based, savings-first and custom-percentage methods, plus read-only what-if comparisons in Coach. Budget provides method selection and a live affordability summary while editing. Adopting an option creates an unsaved draft; income, expense coverage and final saving require confirmation. Overview shows the saved method. Percentage targets use full take-home income and never silently overwrite savings or category limits.

Coach supports on-demand recorded-spending reviews and clearly labeled month-end pace illustrations when records are sufficient. Ordinary reviews do not automatically propose higher limits. Users can request a comparison, adopt a draft and confirm its exact changes. Ask “Review my budget for September 2026”; Budget itself shows saved totals, charts and the monthly editor, without a separate review panel.

## Goal changes in Coach

Coach can create, edit and delete saved goals through the Goal Strategy Agent. For example:

- "Create a goal named Emergency fund, target SGD 12,000, currently saved SGD 1,000, over 12 months."
- "Update my Emergency fund goal target to SGD 15,000."
- "Delete my Emergency fund goal."

Coach asks for missing information and previews the exact operation. Goal amounts default to fixed SGD; no currency input is needed. Edits show before and after values; deletions show the record being removed. Reply `confirm goal` to apply the preview, `cancel goal` to discard it, or provide corrections for a new preview. Generic `yes` does not execute a goal change. Each request handles one goal. Duplicate names require an exact goal ID from the clarification choices. Foreign-currency amounts are unsupported; existing currency labels are preserved without conversion.

Drafts are owned by the profile and conversation. Expired previews (30 minutes), intervening turns and changed goal records require a fresh preview and confirmation. Goal changes and chat persistence commit together. Apply migration `20260930_0013` with `alembic upgrade head` before running the backend. Local Compose runs migrations automatically.

The offline model fixture uses explicit fields, for example: `Create goal; name: Emergency fund; currency: SGD; target_amount: 12000; current_amount: 1000; target_months: 12`. Edit/delete fixtures use `goal_name: Emergency fund` and any changed fields. Natural-language extraction uses the live model and the separately versioned `goal-capture-v1` contract.

## Agents

Coach retains attributed user-reported facts and corrections within each chat, alongside the latest eight messages and a bounded extractive summary of older preferences, objectives and discussion. Validated local replies also remain available as context. The application’s globe selector explicitly chooses English or Simplified Chinese; conversational text does not override that selection. Clarification checks and local follow-ups use this owned session context without changing saved financial records or calculation grounding. Run `alembic upgrade head` (current head `20261010_0018`) before updating the backend; this includes the previous memory/pending-transaction migration branches and adds durable chat-scoped transaction edit and just-saved references. Reinstall `apps/shared` and update the backend/AI service together. See [Session context](docs/session-context.md) and [Coach remediation](docs/coach-response-remediation-2026-10-03.md) for supported inputs, limits and validation.

Read-only references such as `Explain that more simply`, `What about that goal?` and `Explain the second option` are resolved before routing. Ambiguous references ask one brief question; remembered dialogue cannot resume a pending goal, budget or transaction draft as an action.

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

Compose defaults to `MODEL_PROVIDER=local_fixture` for offline development and loads an optional private `.env` after `.env.example` (Docker Compose 2.24+). It honors an explicit `MODEL_PROVIDER` from `.env` or the shell. The fixture uses canned responses; it does not measure live Coach quality. Its mode is shown in Coach. AWS release uses `MODEL_PROVIDER=openai` with both governed Bedrock retrievers. Local live-model tests can use the packaged local-document retrievers below.

For live local coaching, put these values in the ignored `.env`, alongside a private `OPENAI_API_KEY`, then rebuild/restart Compose:

```dotenv
MODEL_PROVIDER=openai
RAG_PROVIDER=local_documents
EDUCATION_CORPUS_VERSION=investment-education-sg@2026-09-27.2
POLICY_RAG_PROVIDER=local_documents
POLICY_CORPUS_VERSION=financial-coach-policy-sg@2026-10-09.1
```

`MODEL_ROLE_OVERRIDES` accepts a JSON map keyed by prompt role, with optional `model_id`, `reasoning_effort`, and `max_tokens`. The example and AWS template give writers more output room than routing. OpenAI receives a schema on the initial request, and traces distinguish reasoning tokens, output limits, refusals, and invalid contracts. OpenAI reasoning calls do not use the application's temperature setting. See [Coach remediation](docs/coach-response-remediation-2026-10-03.md) for regression coverage and remaining live validation.

To run the services separately:

```powershell
cd C:\ai-financial-wellness-coach\apps\ai-service
pip install -e "../shared" -e ".[dev]"
$env:MODEL_PROVIDER="local_fixture" # use openai plus OPENAI_API_KEY for a live synthetic test
uvicorn app.main:app --reload --port 8001

cd C:\ai-financial-wellness-coach\apps\backend
pip install -e "../shared" -e ".[dev]"
uvicorn app.main:app --reload --port 8080

cd C:\ai-financial-wellness-coach\apps\frontend
pip install -e "../shared" -e ".[dev]"
streamlit run app.py --server.port 8501
```

## CI/CD And LLMSecOps

One **CI and LLMSecOps** workflow directly contains service/security checks and seven component suites: Orchestrator, Spending, Budget, Goal, Investment, Risk & Compliance, and RAG. CI requires their offline regressions plus explicit AI platform/shared-library contracts and evaluation metrics. Actual pytest collection checks that every case has one owner; there is no remaining-tests fallback. See [test organization](docs/test-organization.md) for ownership and artifacts. Release to AWS requires live acceptance after deployment and smoke: all 19 fairness pairs once (38 coaching requests), seven agent/RAG datasets and bounded live security regressions. Failed or incomplete evidence fails the release and rolls changed services back. CI has no paid-live checkbox. Reports include datasets, expected outputs, metrics, criteria and per-case evidence; fixture responses are identified separately from live model responses. The [agent workflow guide](docs/agent-test-workflows.md) explains the CI-to-AWS release gate and [required live release acceptance](docs/post-deployment-acceptance.md).

The same CI file contains the [OWASP security scan jobs](docs/project-security-scan.md). Its Promptfoo cases cover the agents and router; backend/frontend tests run once in their service CI jobs. One **RAG Source Governance** workflow checks both packaged corpora weekly. The historical model-comparison notice and duplicate Policy-only governance workflow have been retired. The separate Budget and Investment live workflows have been consolidated into required Release to AWS acceptance. AWS Operational Validation, Final Assessment and opt-in Model Drift Monitoring retain their separate operational evidence purposes.

GitHub Actions detects affected services and runs their Python tests and security gates. PR/manual/scheduled CI validates container builds; main pushes build once in Release. Backend or AI changes also run the cross-service integration and load smoke tests. Every push runs change detection against the deployed baseline. Documentation and service READMEs select no deployment by themselves, while governed RAG Markdown remains runtime data; pending application fixes still receive CI even after a documentation-only push. Successful push CI for the current `main` SHA automatically starts `Release to AWS`. An application release publishes and deploys all three service images from that SHA, including the backend migration check: after a failed release rolls back, a later push diff alone cannot identify earlier fixes still missing from AWS. A separate weekly/manual workflow records privacy-safe live OpenAI/RAG, governed data-lifecycle retention, load, scaling, and CloudWatch evidence. Setup requirements and private-repository plan limitations are documented in `docs/cicd-pipeline.md`.

## Evaluation

Run the release gate from the repository root after installing the AI service:

```powershell
python -m app.evals.gate --policy infra/llmsecops/evaluation-policy.json --output evaluation-results.json
```

Use only synthetic financial profiles in the current demo. The production-readiness exclusions and AWS go/no-go sequence are documented in `infra/aws/README.md`.

Evaluation policy v9 enforces all 136 cases/pairs conjunctively across routing, dynamic agent/tool
dependencies, direct and conditional Education RAG, Policy RAG, deterministic guardrails,
regulated-advice behavior, and paired fairness consistency.
The weekly AWS workflow repeats the expanded live suite three times and blocks on any case,
latency, cost, or synthetic-cleanup failure.

Full-document local retrieval and its separate 99% evidence-quality gate are documented in [RAG quality acceptance](docs/rag-quality.md). This score does not establish real-model answer quality.
