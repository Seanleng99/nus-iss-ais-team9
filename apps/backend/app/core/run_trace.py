"""Backend-owned trace context, shared with the private AI client."""

from contextvars import ContextVar

active_run: ContextVar[object | None] = ContextVar("active_run", default=None)
