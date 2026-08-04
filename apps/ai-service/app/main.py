import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from app.core.config import settings
from app.core.observability import RequestTelemetryMiddleware
from app.core.schemas import CoachRequest, CoachResponse
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator

app = FastAPI(title="AI Financial Wellness Coach AI Service", version="0.1.0")
app.add_middleware(RequestTelemetryMiddleware, service_name="ai-service")
orchestrator = AgentOrchestrator()


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
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI service is temporarily unable to generate a validated response.",
        ) from exc
