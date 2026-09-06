import json
import logging
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.core.config import settings
from app.core.observability import RequestTelemetryMiddleware, get_correlation_id
from app.core.schemas import CoachRequest, CoachResponse
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.retriever import RetrievalError

logging.getLogger("service").setLevel(
    getattr(logging, settings.log_level.upper(), logging.INFO)
)

app = FastAPI(title="AI Financial Wellness Coach AI Service", version="0.1.0")
app.add_middleware(RequestTelemetryMiddleware, service_name="ai-service")
orchestrator = AgentOrchestrator()
logger = logging.getLogger("service.ai")


def _log_generation_failure(exc: ModelGatewayError | RetrievalError) -> None:
    is_retrieval_error = isinstance(exc, RetrievalError)
    logger.error(
        json.dumps(
            {
                "event": "coach_generation_failed",
                "correlation_id": get_correlation_id(),
                "error_code": getattr(
                    exc,
                    "code",
                    "RETRIEVAL_ERROR" if is_retrieval_error else "MODEL_GATEWAY_ERROR",
                ),
                "component": getattr(
                    exc,
                    "component",
                    None,
                )
                or ("education_retriever" if is_retrieval_error else "orchestrator"),
                "exception_type": type(exc).__name__,
            },
            separators=(",", ":"),
        )
    )


def get_orchestrator() -> AgentOrchestrator:
    return orchestrator


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid API key is required.",
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/coach", response_model=CoachResponse, dependencies=[Depends(require_api_key)])
def coach(
    request: CoachRequest,
    agent_orchestrator: Annotated[AgentOrchestrator, Depends(get_orchestrator)],
) -> CoachResponse:
    try:
        return agent_orchestrator.handle(request)
    except (ModelGatewayError, RetrievalError) as exc:
        _log_generation_failure(exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI service is temporarily unable to generate a validated response.",
        ) from exc
