import json
import logging
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
logger = logging.getLogger("service.access")


def get_correlation_id() -> str | None:
    return _correlation_id.get()


class RequestTelemetryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service_name: str) -> None:
        super().__init__(app)
        self._service_name = service_name

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        token = _correlation_id.set(correlation_id)
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._log_event(request, 500, started, correlation_id, "request_failed")
            raise
        else:
            response.headers["X-Correlation-ID"] = correlation_id
            self._log_event(request, response.status_code, started, correlation_id, "request")
            return response
        finally:
            _correlation_id.reset(token)

    def _log_event(
        self,
        request: Request,
        status_code: int,
        started: float,
        correlation_id: str,
        event: str,
    ) -> None:
        logger.info(
            json.dumps(
                {
                    "event": event,
                    "service": self._service_name,
                    "correlation_id": correlation_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                },
                separators=(",", ":"),
            )
        )
