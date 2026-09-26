# FastAPI Multi-Agent AI Service

Private Python API containing the model-driven LangGraph orchestration layer.

## Responsibilities

- Normalize and validate user requests.
- Authenticate Streamlit service requests with an API key.
- Redact sensitive values before prompts and logs.
- Detect direct and indirect prompt-injection attempts.
- Route requests through OpenAI GPT-6 Luna to one or more specialist agents.
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

For a deployed environment, set `MODEL_PROVIDER=openai`, `MODEL_ID=gpt-6-luna`, `MODEL_REASONING_EFFORT=low`, and supply `OPENAI_API_KEY` through a secret. Set both `RAG_PROVIDER=local_documents` and `POLICY_RAG_PROVIDER=local_documents`, with exact Education and Policy corpus versions. The image packages the reviewed files and manifests. Retrieval verifies hashes, provenance, approval, and review deadlines before use; policy retrieval supplies all three approved policy documents. No Bedrock service is called by the deployed AI task.
For a local live-model run, place the key in the ignored repository-root `.env` file or the shell environment. The service reads `.env` from either the repository root or `apps/ai-service`; `.env.example` must remain blank.
The packaged Education corpus is owned by Investment Education. Its
retrieval request contains canonical education topics rather than the raw user question or
personal values. Prompt set v6 retains fine-grained concepts and a canonical question-intent
hint, explicitly records unsupported topics, and preserves partial-evidence notices through
synthesis. In v6/v7, Investment Education first uses retrieved passages and may supplement missing
stable concepts in a separate `general_knowledge` field. The application labels that text as model
knowledge, not verified against retrieved sources, before safety review. It must not contain citations,
current market data, scheme eligibility/limits, tax/legal rules, provider claims or personal advice.
`evidence_status` is `hybrid` or `general_knowledge` when supplements are used. Unsupported topics
remain explicit gaps; retrieval errors or unsafe chunks never enable fallback. Budget and Goal Strategy
education still require RAG evidence, and unavailable policy evidence still blocks every answer.
Final citation markers are validated and links are generated from approved metadata.
Blocked narratives are withheld across the response and backend/UI read boundaries. Compliance receives
its sanitized evidence through the agent result rather than querying the Education corpus, and independently retrieves only from the Policy corpus.
The `/health` endpoint is public. Send `AI_SERVICE_API_KEY` through the `X-API-Key` header when
calling `/coach`.
