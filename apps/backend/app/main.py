from fastapi import FastAPI

from app.api.budget_continuity import router as budget_continuity_router
from app.api.financial import router as financial_router
from app.api.oidc import router as oidc_router
from app.api.routes import router
from app.core.config import settings
from app.core.observability import RequestTelemetryMiddleware
from app.core.telemetry import configure_logging

configure_logging(settings.log_level)
app = FastAPI(title="AI Financial Wellness Coach Backend", version="0.1.0")
app.add_middleware(RequestTelemetryMiddleware, service_name="backend")
app.include_router(router, prefix="/api")
app.include_router(financial_router, prefix="/api")
app.include_router(budget_continuity_router, prefix="/api")
app.include_router(oidc_router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
