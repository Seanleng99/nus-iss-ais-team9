from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.telemetry import _correlation_id, call_span, log_event, trace_context


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
        started = perf_counter()
        with trace_context(
            correlation_id=request.headers.get("X-Correlation-ID"),
            journey_id=request.headers.get("X-Journey-ID"),
            parent_span_id=request.headers.get("X-Parent-Span-ID"),
            caller_method=request.headers.get("X-Caller-Method"),
        ):
            if request.url.path == "/health":
                response = await call_next(request)
                response.headers["X-Correlation-ID"] = get_correlation_id()
                if response.status_code >= 400:
                    self._log_event(request, response.status_code, started, "request_failed")
                return response
            with call_span("app.core.observability.RequestTelemetryMiddleware.dispatch"):
                try:
                    response = await call_next(request)
                except Exception:
                    self._log_event(request, 500, started, "request_failed")
                    raise
                response.headers["X-Correlation-ID"] = get_correlation_id()
                self._log_event(request, response.status_code, started, "request")
                return response

    def _log_event(
        self,
        request: Request,
        status_code: int,
        started: float,
        event: str,
    ) -> None:
        log_event(
            event,
            http_method=request.method,
            route=getattr(request.scope.get("route"), "path", "<unmatched>"),
            status_code=status_code,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )
