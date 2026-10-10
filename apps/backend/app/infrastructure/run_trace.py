"""Bounded audit persistence with explicit buffering during business transactions."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from coach_trace import make_event, safe_event
from sqlalchemy.exc import SQLAlchemyError

from app.core.telemetry import call_span, context_fields, log_event
from app.infrastructure.models import OrchestrationTraceRecord
from app.infrastructure.repositories import SQLAlchemyOrchestrationTraceRepository


class DurableRun:
    def __init__(self, session, session_id, timeout_seconds):
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "__init__")
        self.session = session
        self.trace_id = str(uuid4())
        self.buffered = False
        self.pending = []
        self.closed = False
        self.record = SQLAlchemyOrchestrationTraceRepository(session).create(
            trace_id=self.trace_id,
            session_id=session_id,
            assistant_message_id=None,
            selected_agents=[],
            agent_results=[],
            audit={"trace_id": self.trace_id, "durable_events": []},
            blocked=False,
        )
        self.record.status = "running"
        self.record.correlation_id = context_fields().get("correlation_id")
        self.record.deadline_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds + 60)
        log_event("trace.run.started", trace_id=self.trace_id, status="running")
        try:
            self.commit()
        except Exception as exc:
            self.session.rollback()
            log_event(
                "trace.persistence.failed",
                level=logging.ERROR,
                trace_id=self.trace_id,
                exception_type=type(exc).__name__,
            )
            raise

    def commit(self):
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "commit")
        with call_span("sqlalchemy.orm.session.Session.commit"):
            self.session.commit()

    def record_event(self, event_type, **details):
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "record_event")
        event = make_event(
            event_type,
            self.trace_id,
            actor="backend",
            details=details,
            **{
                key: value
                for key, value in context_fields().items()
                if key in {"span_id", "parent_span_id", "correlation_id"}
            },
        )
        log_event(event_type, event_id=event["event_id"], **event["details"])
        self.append(event)

    def _save_event(self, event):
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "_save_event")
        events = self.record.audit.get("durable_events", [])
        if any(item["event_id"] == event["event_id"] for item in events):
            return
        if len(events) >= 2000:
            raise ValueError("Trace event limit exceeded")
        self.record.audit = {**self.record.audit, "durable_events": [*events, event]}
        if event["event_type"] == "workflow.started":
            self.record.model_provider = event["details"].get("model_provider")
            self.record.model_id = event["details"].get("model_id")
            self.record.prompt_set_version = event["details"].get("prompt_set_version")
        if event["event_type"] == "routing.completed":
            self.record.selected_agents = event["details"].get("selected_agents", [])

    def append(self, event):
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "append")
        if self.closed:
            raise ValueError("Trace run has closed")
        event = safe_event(event, self.trace_id)
        if self.buffered:
            saved = self.record.audit.get("durable_events", [])
            if any(item["event_id"] == event["event_id"] for item in [*saved, *self.pending]):
                return
            if len(self.pending) + len(self.record.audit.get("durable_events", [])) >= 2000:
                raise ValueError("Trace event limit exceeded")
            self.pending.append(event)
        else:
            self._save_event(event)
            self.commit()

    def _drain(self):
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "_drain")
        for event in self.pending:
            self._save_event(event)

    def flush(self):
        """Explicit pre-AI checkpoint; never called while an action is pending."""
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "flush")
        self._drain()
        self.commit()
        self.pending.clear()
        self.buffered = False

    def fail(self, status, code):
        # Roll back pending chat writes; earlier event commits remain durable.
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "fail")
        self.session.rollback()
        try:
            record = self.session.get(OrchestrationTraceRecord, self.trace_id)
            if record is not None and record.status == "running":
                self.record = record
                self._drain()
                record.status = status
                record.error_code = code
                record.finished_at = datetime.now(UTC)
                self.commit()
                self.pending.clear()
        except (SQLAlchemyError, ValueError) as exc:
            self.session.rollback()
            log_event(
                "trace.persistence.failed",
                level=logging.ERROR,
                trace_id=self.trace_id,
                exception_type=type(exc).__name__,
            )
        self.closed = True
        log_event("trace.run.finished", trace_id=self.trace_id, status=status, error_code=code)

    def complete(self, response, assistant_message_id):
        log_event("VV entering ", "app.infrastructure.run_trace.DurableRun", "complete")
        self.buffered = True
        self.record_event("backend.persistence.started")
        self._drain()
        record = self.record
        response.audit["trace_id"] = self.trace_id
        record.assistant_message_id = assistant_message_id
        record.selected_agents = [agent.value for agent in response.selected_agents]
        record.agent_results = [item.model_dump(mode="json") for item in response.agent_results]
        record.audit = {**response.audit, "durable_events": record.audit.get("durable_events", [])}
        record.blocked = response.blocked
        record.status = "blocked" if response.blocked else "completed"
        record.finished_at = datetime.now(UTC)
        record.model_provider = response.audit.get("model_provider")
        record.model_id = response.audit.get("model_id")
        record.prompt_set_version = response.audit.get("prompt_set_version")
        completion = make_event(
            "backend.persistence.completed",
            self.trace_id,
            actor="backend",
            details={"persisted": True},
        )
        self._save_event(completion)
        self.commit()
        self.pending.clear()
        self.closed = True
        log_event("backend.persistence.completed", event_id=completion["event_id"], persisted=True)
        log_event("trace.run.finished", trace_id=self.trace_id, status=record.status)
