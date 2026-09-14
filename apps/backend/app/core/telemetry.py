"""Content-free call tracing. Keep the three independently built service copies aligned."""

import inspect
import json
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from math import isfinite
from time import perf_counter
from uuid import uuid4

SERVICE_NAME = "backend"
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_journey_id: ContextVar[str | None] = ContextVar("journey_id", default=None)
_span: ContextVar[dict | None] = ContextVar("call_span", default=None)
logger = logging.getLogger("service.calls")

# No payload, query, prompt, answer, token, claim, URL, profile ID or exception text.
_COUNTS = {
    "duration_ms",
    "status_code",
    "input_characters",
    "output_characters",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "source_count",
    "finding_count",
    "agent_result_count",
    "retrieved_chunk_count",
    "accepted_chunk_count",
    "rejected_chunk_count",
    "attempt",
    "top_k",
    "history_count",
    "message_count",
    "model_call_count",
    "timeout_seconds",
    "response_bytes",
    "question_characters",
}
_FLAGS = {"blocked", "allowed", "cache_hit", "snapshot_found", "authenticated", "persisted"}
_CODES = {
    "agent",
    "component",
    "status",
    "error_code",
    "exception_type",
    "reason_code",
    "response_type",
    "response_language",
    "authentication_method",
    "routing_mode",
    "evidence_status",
    "provider",
    "model_id",
    "prompt_id",
    "prompt_set_version",
    "corpus_version",
    "knowledge_base_id",
    "http_method",
    "route",
    "trace_id",
    "request_id",
    "task_id",
    "selected_agents",
    "response_fields",
    "source_ids",
}


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


def _safe_code(value):
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_./:@{}<>-]{1,180}", value):
        return value
    return None


def context_fields() -> dict:
    return {
        "correlation_id": _correlation_id.get(),
        "journey_id": _journey_id.get(),
        **(_span.get() or {}),
    }


def log_event(event: str, *, level: int = logging.INFO, **fields) -> None:
    safe = {}
    for key, value in fields.items():
        if (
            key in _COUNTS
            and type(value) in (int, float)
            and isfinite(value)
            or key in _FLAGS
            and isinstance(value, bool)
        ):
            safe[key] = value
        elif key in _CODES:
            if isinstance(value, (list, tuple)):
                safe[key] = [code for item in value[:30] if (code := _safe_code(item))]
            elif (code := _safe_code(value)) is not None:
                safe[key] = code
    logger.log(
        level,
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "service": SERVICE_NAME,
                "event": _safe_code(event) or "telemetry.event",
                **context_fields(),
                **safe,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )


def log_synthetic_exchange(question: str, answer: str) -> None:
    """Only call after the backend authorizes an explicitly marked synthetic exchange.

    Keep this exception to content-free logging out of AI and frontend services.
    The endpoint validates the automation identity, reserved ID prefix and demo
    environment, and logs only the final safety-filtered answer after commit.
    """
    logger.info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "service": SERVICE_NAME,
                "event": "coach.synthetic.exchange",
                **context_fields(),
                "synthetic_content": True,
                "question": question,
                "answer": answer,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )


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
