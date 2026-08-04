# FastAPI Multi-Agent AI Service

Private Python API containing the model-driven LangGraph orchestration layer.

## Responsibilities

- Normalize and validate user requests.
- Authenticate Streamlit service requests with an API key.
- Redact sensitive values before prompts and logs.
- Detect direct and indirect prompt-injection attempts.
- Route requests through a Bedrock model to one or more specialist agents.
- Generate grounded specialist narratives and a final synthesis.
- Run independent model-assisted risk and compliance validation.
- Ground Risk and Compliance review with controlled, sanitized RAG sources.
- Provide an explicit offline fixture for deterministic control and regression evaluation.

## Run

```powershell
pip install -e ".[dev]"
$env:MODEL_PROVIDER="local_fixture"
uvicorn app.main:app --reload --port 8001
```

Remove the `MODEL_PROVIDER` override to use the default Bedrock gateway with the current AWS identity. The `/health` endpoint is public. Send `AI_SERVICE_API_KEY` through the `X-API-Key` header when calling `/coach`.
