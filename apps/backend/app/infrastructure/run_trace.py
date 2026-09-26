"""Incremental, bounded metadata persistence in the request's backend session."""

import logging
import re
from datetime import UTC, datetime, timedelta
from math import isfinite
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.core.telemetry import _CODES, _COUNTS, _FLAGS, call_span, context_fields, log_event
from app.infrastructure.models import OrchestrationTraceRecord
from app.infrastructure.repositories import SQLAlchemyOrchestrationTraceRepository

# Never persist prompt, answer, exception text, or free-form rationale before safety review.
_CODES_ALLOWED = _CODES | {
    "capability",
    "capabilities",
    "corpus_version",
    "policy_corpus_version",
    "policy_corpus_versions",
    "query_topics",
    "requested_by",
    "resolution",
    "retrieval_consumer",
    "retrieval_consumers",
    "retrieval_corpus_versions",
    "input_fingerprint",
    "call_id",
    "event_id",
    "model_provider",
}
_COUNTS_ALLOWED = _COUNTS | {
    "attempts",
    "model_input_tokens",
    "model_output_tokens",
    "policy_note_count",
    "policy_source_count",
    "retrieval_source_count",
}
_FLAGS_ALLOWED = _FLAGS | {"required", "retryable"}


def _code(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_./:@{}<>-]{1,180}", value)
        else None
    )


def safe_event(event, trace_id):
    if not isinstance(event, dict) or event.get("trace_id") != trace_id:
        raise ValueError("Invalid trace event")
    event_id = str(UUID(event["event_id"]))
    event_type = _code(event.get("event_type"))
    if not event_type:
        raise ValueError("Invalid event type")
    timestamp = datetime.fromisoformat(event["timestamp"])
    if timestamp.tzinfo is None:
        raise ValueError("Missing event timezone")
    result = {
        "event_id": event_id,
        "trace_id": trace_id,
        "event_type": event_type,
        "timestamp": timestamp.isoformat(),
    }
    for key in (
        "task_id",
        "parent_task_id",
        "span_id",
        "parent_span_id",
        "actor",
        "correlation_id",
    ):
        if (value := _code(event.get(key))) is not None:
            result[key] = value
    details = {}
    for key, value in event.get("details", {}).items():
        if (
            key in _FLAGS_ALLOWED
            and isinstance(value, bool)
            or key in _COUNTS_ALLOWED
            and type(value) in (int, float)
            and isfinite(value)
        ):
            details[key] = value
        elif key in _CODES_ALLOWED:
            if isinstance(value, list):
                details[key] = [item for item in value[:30] if _code(item)]
            elif _code(value):
                details[key] = value
    if type(event.get("attempt")) is int:
        details["attempt"] = event["attempt"]
    result["details"] = details
    return result


class DurableRun:
    def __init__(self, session, session_id, timeout_seconds):
        self.session = session
        self.trace_id = str(uuid4())
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
        with call_span("sqlalchemy.orm.session.Session.commit"):
            self.session.commit()

    def append(self, event):
        event = safe_event(event, self.trace_id)
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
        self.commit()

    def fail(self, status, code):
        # Roll back pending chat writes; earlier event commits remain durable.
        self.session.rollback()
        try:
            record = self.session.get(OrchestrationTraceRecord, self.trace_id)
            if record is not None and record.status == "running":
                record.status = status
                record.error_code = code
                record.finished_at = datetime.now(UTC)
                self.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            log_event(
                "trace.persistence.failed",
                level=logging.ERROR,
                trace_id=self.trace_id,
                exception_type=type(exc).__name__,
            )
        log_event("trace.run.finished", trace_id=self.trace_id, status=status, error_code=code)

    def complete(self, response, assistant_message_id):
        record = self.record
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
        self.commit()
        log_event("trace.run.finished", trace_id=self.trace_id, status=record.status)
