from fastapi import FastAPI

from app.api.routes import router
from app.core.observability import RequestTelemetryMiddleware

app = FastAPI(title="AI Financial Wellness Coach Backend", version="0.1.0")
app.add_middleware(RequestTelemetryMiddleware, service_name="backend")
app.include_router(router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
