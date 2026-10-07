import json
import logging
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.action_composition import ActionCompositionRequest, compose_action
from app.core.config import settings
from app.core.observability import RequestTelemetryMiddleware, get_correlation_id
from app.core.schemas import CoachRequest, CoachResponse
from app.core.telemetry import configure_logging, context_fields, log_event, trace_method
from app.core.trace_stream import stream_run
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.retriever import RetrievalError

configure_logging(settings.log_level)

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
                "service": "ai-service",
                **context_fields(),
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


@trace_method
def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        log_event("authentication.rejected", authentication_method="service_api_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid API key is required.",
        )
    log_event("authentication.accepted", authentication_method="service_api_key")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/coach", response_model=CoachResponse, dependencies=[Depends(require_api_key)])
@trace_method
def coach(
    request: CoachRequest,
    agent_orchestrator: Annotated[AgentOrchestrator, Depends(get_orchestrator)],
) -> CoachResponse:
    try:
        log_event("coach.request.accepted", input_characters=len(request.message))
        response = agent_orchestrator.handle(request)
        log_event(
            "coach.response.ready",
            trace_id=response.audit.get("trace_id"),
            selected_agents=[agent.value for agent in response.selected_agents],
            blocked=response.blocked,
            output_characters=len(response.answer),
            source_count=len(response.sources),
            response_fields=list(CoachResponse.model_fields),
        )
        return response
    except (ModelGatewayError, RetrievalError) as exc:
        _log_generation_failure(exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI service is temporarily unable to generate a validated response.",
        ) from exc


@app.post("/coach/stream", dependencies=[Depends(require_api_key)])
async def coach_stream(
    request: CoachRequest,
    agent_orchestrator: Annotated[AgentOrchestrator, Depends(get_orchestrator)],
    x_workflow_id: Annotated[UUID, Header()],
    x_workflow_timeout_seconds: Annotated[float | None, Header(ge=1, le=115)] = None,
) -> StreamingResponse:
    """Private transport: validated metadata events followed by one final response."""
    return StreamingResponse(
        stream_run(agent_orchestrator, request, str(x_workflow_id),
                   timeout_seconds=x_workflow_timeout_seconds),
        media_type="application/x-ndjson",
        headers={"X-Trace-ID": str(x_workflow_id), "Cache-Control": "no-store"},
    )


@app.post("/coach/compose", response_model=CoachResponse, dependencies=[Depends(require_api_key)])
def coach_compose(
    payload: ActionCompositionRequest,
    agent_orchestrator: Annotated[AgentOrchestrator, Depends(get_orchestrator)],
) -> CoachResponse:
    """Private, non-streaming composition after backend validation; no writes."""
    try:
        return compose_action(payload, agent_orchestrator)
    except (ModelGatewayError, RetrievalError) as error:
        _log_generation_failure(error)
        raise HTTPException(status_code=503, detail="Action composition is temporarily unavailable.") from error


@app.post("/coach/compose/stream", dependencies=[Depends(require_api_key)])
async def coach_compose_stream(
    payload: ActionCompositionRequest,
    agent_orchestrator: Annotated[AgentOrchestrator, Depends(get_orchestrator)],
    x_workflow_id: Annotated[UUID, Header()],
) -> StreamingResponse:
    trace_id = str(x_workflow_id)
    if payload.response.audit.get("trace_id") != trace_id or payload.response.session_id != payload.request.session_id:
        raise HTTPException(status_code=422, detail="Invalid composition identity")
    return StreamingResponse(
        stream_run(agent_orchestrator, payload, trace_id, operation="composition"),
        media_type="application/x-ndjson",
        headers={"X-Trace-ID": trace_id, "Cache-Control": "no-store"},
    )
