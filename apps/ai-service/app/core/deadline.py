"""One request deadline inherited by specialist threads and model corrections."""

from contextvars import ContextVar
from time import perf_counter

from app.core.telemetry import log_event

workflow_deadline: ContextVar[float | None] = ContextVar("workflow_deadline", default=None)


def remaining_seconds():
    log_event("VV entering ", "app.core.deadline", "remaining_seconds")
    deadline = workflow_deadline.get()
    return None if deadline is None else max(0.0, deadline - perf_counter())


def check_deadline(component):
    log_event("VV entering ", "app.core.deadline", "check_deadline")
    from app.models.gateway import ModelGatewayError
    remaining = remaining_seconds()
    if remaining is not None and remaining <= 0:
        raise ModelGatewayError("Workflow deadline exhausted.", code="WORKFLOW_TIMEOUT", component=component)
    return remaining
