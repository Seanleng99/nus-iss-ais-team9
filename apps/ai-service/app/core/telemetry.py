"""Content-free call tracing using the shared metadata contract."""

import inspect
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from time import perf_counter
from uuid import uuid4

from coach_trace import ENTRY_EVENT, SCHEMA_VERSION, is_durable_event, log_event_name, safe_details
from coach_trace import code as _safe_code

from app.core.run_trace import emit, task_context, workflow_id

SERVICE_NAME = "ai-service"
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_journey_id: ContextVar[str | None] = ContextVar("journey_id", default=None)
_span: ContextVar[dict | None] = ContextVar("call_span", default=None)
_quiet: ContextVar[bool] = ContextVar("quiet_calls", default=False)
logger = logging.getLogger("service.calls")

def configure_logging(level: str = "INFO") -> None:
    # basicConfig is idempotent; it also preserves the hosting application's handlers.
    # Only our namespace is raised to INFO, not libraries that may log auth URLs.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("service").setLevel(getattr(logging, level.upper(), logging.INFO))


def valid_correlation_id(value: str | None) -> str:
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
        else str(uuid4())
    )


def context_fields() -> dict:
    return {
        "correlation_id": _correlation_id.get(),
        "journey_id": _journey_id.get(),
        **(_span.get() or {}),
        **({"trace_id": workflow_id.get()} if workflow_id.get() else {}),
        **(task_context.get() or {}),
    }


def log_event(
    event: str, classname: str | None = None, methodname: str | None = None,
    *, level: int = logging.INFO, **fields,
) -> None:
    """Log static entry identifiers or allowlisted metadata; never inspect arguments."""
    if event == ENTRY_EVENT and not logger.isEnabledFor(level):
        return
    if _quiet.get() and level < logging.WARNING and not is_durable_event(event):
        return
    safe = safe_details({**fields, "classname": classname, "methodname": methodname})
    durable = is_durable_event(event)
    timestamp = datetime.now(UTC).isoformat()
    if durable:
        safe["event_id"] = str(uuid4())
    logger.log(
        level,
        json.dumps(
            {
                "timestamp": timestamp,
                "service": SERVICE_NAME,
                "event": log_event_name(event),
                **context_fields(),
                **safe,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )
    if durable and (fields.get("trace_id") or workflow_id.get()):
        emit({
            "schema_version": SCHEMA_VERSION,
            "event_id": safe["event_id"], "event_type": event,
            "timestamp": timestamp,
            **context_fields(), "details": safe,
        })



@contextmanager
def quiet_calls():
    """Drop routine entry and call logs inside bulk loops; failures and durable audit events still log."""
    token = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(token)


@contextmanager
def trace_context(*, correlation_id=None, journey_id=None, parent_span_id=None, caller_method=None):
    """Bind a request; caller-supplied tracing identifiers are never authorization."""
    correlation_token = _correlation_id.set(valid_correlation_id(correlation_id))
    journey_token = _journey_id.set(
        journey_id
        if isinstance(journey_id, str) and re.fullmatch(r"[a-f0-9]{32}", journey_id)
        else None
    )
    parent = None
    if isinstance(parent_span_id, str) and re.fullmatch(r"[a-f0-9]{16}", parent_span_id):
        parent = {"span_id": parent_span_id, "method": _safe_code(caller_method) or "http.client"}
    span_token = _span.set(parent)
    try:
        yield
    finally:
        _span.reset(span_token)
        _journey_id.reset(journey_token)
        _correlation_id.reset(correlation_token)


def outbound_headers() -> dict[str, str]:
    fields = context_fields()
    return {
        header: fields[key]
        for header, key in (
            ("X-Correlation-ID", "correlation_id"),
            ("X-Journey-ID", "journey_id"),
            ("X-Parent-Span-ID", "span_id"),
            ("X-Caller-Method", "method"),
        )
        if fields.get(key)
    }


@contextmanager
def call_span(method: str, **fields):
    parent = _span.get() or {}
    token = _span.set(
        {
            "span_id": uuid4().hex[:16],
            "parent_span_id": parent.get("span_id"),
            "caller_method": parent.get("method"),
            "method": _safe_code(method) or "unknown",
        }
    )
    started = perf_counter()
    log_event("method.started", **fields)
    try:
        yield
    except BaseException as exc:
        # Streamlit uses control-flow exceptions for successful reruns/stops.
        control_flow = type(exc).__name__ in {"RerunException", "StopException"}
        log_event(
            "method.completed" if control_flow else "method.failed",
            level=logging.INFO if control_flow else logging.ERROR,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            exception_type=type(exc).__name__,
            **fields,
        )
        raise
    else:
        log_event(
            "method.completed", duration_ms=round((perf_counter() - started) * 1000, 2), **fields
        )
    finally:
        _span.reset(token)


def trace_method(function):
    """Trace explicit call boundaries without inspecting or serializing arguments/results."""
    method = f"{function.__module__}.{function.__qualname__}"
    if inspect.iscoroutinefunction(function):

        @wraps(function)
        async def asynchronous(*args, **kwargs):
            with call_span(method):
                return await function(*args, **kwargs)

        return asynchronous

    @wraps(function)
    def synchronous(*args, **kwargs):
        with call_span(method):
            return function(*args, **kwargs)

    return synchronous
