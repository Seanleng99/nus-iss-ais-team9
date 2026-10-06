"""Request-scoped, content-free event delivery to the backend-owned audit store."""

from contextvars import ContextVar

workflow_id: ContextVar[str | None] = ContextVar("workflow_id", default=None)
event_sink: ContextVar[object | None] = ContextVar("event_sink", default=None)
last_model_call: ContextVar[str | None] = ContextVar("last_model_call", default=None)

task_context: ContextVar[dict | None] = ContextVar("task_context", default=None)


def emit(event: dict) -> None:
    sink = event_sink.get()
    if sink is not None:
        sink(event)
