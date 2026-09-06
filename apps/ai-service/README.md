# FastAPI Multi-Agent AI Service

Private Python API containing the model-driven LangGraph orchestration layer.

## Responsibilities

- Normalize and validate user requests.
- Authenticate Streamlit service requests with an API key.
- Redact sensitive values before prompts and logs.
- Detect direct and indirect prompt-injection attempts.
- Route requests through a Bedrock model to one or more specialist agents.
- Resolve typed, capability-based specialist dependencies through the orchestrator.
- Suspend and resume dependent tasks without allowing direct agent-to-agent calls.
- Generate grounded specialist narratives and a final synthesis.
- Ground Investment Education in approved Education sources, quarantine unsafe chunks, and return only validated citations.
- Run independent model-assisted risk and compliance validation.
- Supply Investment Education evidence to Risk and Compliance for independent review.
- Ground Risk and Compliance in a separate approved Policy collection and fail closed without current policy evidence.
- Provide an explicit offline fixture for deterministic control and regression evaluation.

## Dynamic Dependencies

Specialists request capabilities rather than naming or invoking other specialists. The
orchestrator validates each request against the capability registry, reuses an existing result or
schedules its provider, detects cycles, and resumes the requester with only the validated result.

The first implemented dependency is `goal_strategy -> monthly_savings_capacity`. Budget produces
that capability from the deterministic budget calculator. If Budget was already selected, its
result is reused; otherwise the orchestrator adds Budget to the workflow. Dependency request,
scheduling, resolution, and task-resumption events are included in the response audit metadata.

## Run

```powershell
pip install -e ".[dev]"
$env:MODEL_PROVIDER="local_fixture"
$env:RAG_PROVIDER="local_fixture"
$env:EDUCATION_CORPUS_VERSION="investment-education-sg@local-fixture-v1"
$env:POLICY_RAG_PROVIDER="local_fixture"
$env:POLICY_CORPUS_VERSION="financial-coach-policy-sg@local-fixture-v1"
uvicorn app.main:app --reload --port 8001
```

For a deployed environment, set both `RAG_PROVIDER=bedrock` and `POLICY_RAG_PROVIDER=bedrock`. Provide the reviewed Education and Policy knowledge-base IDs and corpus versions. The AI task role needs read-only access to those exact knowledge bases. Both retrievers reject chunks that do not carry complete governed metadata, match the configured corpus, and remain within their review deadline.
The current six-source managed Education collection is owned by Investment Education. Its
retrieval request contains canonical education topics rather than the raw user question or
personal values. Compliance receives
its sanitized evidence through the agent result rather than querying the Education knowledge base, and independently retrieves only from the Policy collection.
The `/health` endpoint is public. Send `AI_SERVICE_API_KEY` through the `X-API-Key` header when
calling `/coach`.
