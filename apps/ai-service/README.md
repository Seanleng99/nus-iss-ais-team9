# FastAPI Multi-Agent AI Service

Private Python API containing the model-driven LangGraph orchestration layer.

## Responsibilities

- Normalize and validate user requests.
- Authenticate Streamlit service requests with an API key.
- Redact sensitive values before prompts and logs.
- Detect direct and indirect prompt-injection attempts.
- Route requests through a Bedrock model to one or more specialist agents.
- Generate grounded specialist narratives and a final synthesis.
- Ground Investment Education in approved, sanitized education sources and return citations.
- Run independent model-assisted risk and compliance validation.
- Supply Investment Education evidence to Risk and Compliance for independent review.
- Apply packaged controlled policy context until the separate managed Policy knowledge base is implemented.
- Provide an explicit offline fixture for deterministic control and regression evaluation.

## Run

```powershell
pip install -e ".[dev]"
$env:MODEL_PROVIDER="local_fixture"
$env:RAG_PROVIDER="local_fixture"
uvicorn app.main:app --reload --port 8001
```

For a deployed environment, set `RAG_PROVIDER=bedrock` and provide
`EDUCATION_KNOWLEDGE_BASE_ID`. The AI task role needs read-only access to that knowledge base.
The current managed Education collection is owned by Investment Education. Compliance receives
its sanitized evidence through the agent result rather than querying the Education knowledge base.
The `/health` endpoint is public. Send `AI_SERVICE_API_KEY` through the `X-API-Key` header when
calling `/coach`.
