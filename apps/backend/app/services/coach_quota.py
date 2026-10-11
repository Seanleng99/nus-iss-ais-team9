"""Atomic, shared per-principal limits; uncertain provider usage stays charged."""

import hashlib
import json
import math
from datetime import UTC, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.telemetry import log_event
from app.infrastructure.models import CoachQuotaLease, CoachQuotaRecord, OrchestrationTraceRecord


def principal_key(principal):
    # Every profile/conversation belonging to the same identity shares a bucket.
    # Automation requests share the credential's bucket, never a caller user ID.
    log_event("VV entering ", "app.services.coach_quota", "principal_key")
    identity = ("automation",) if principal.is_automation else (
        principal.authentication_method, principal.issuer, principal.subject,
    )
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


class CoachQuota:
    def __init__(self, engine, config):
        log_event("VV entering ", "app.services.coach_quota.CoachQuota", "__init__")
        self.engine, self.config = engine, config

    def acquire(self, principal, *, now=None):
        log_event("VV entering ", "app.services.coach_quota.CoachQuota", "acquire")
        owner = principal_key(principal)
        lease_id = str(uuid4())
        try:
            with Session(self.engine) as session, session.begin():
                # One database clock across replicas; a caller never supplies it.
                evaluated_at = now or session.scalar(select(func.current_timestamp()))
                if evaluated_at.tzinfo is None:
                    evaluated_at = evaluated_at.replace(tzinfo=UTC)
                minute, hour = int(evaluated_at.timestamp()) // 60, int(evaluated_at.timestamp()) // 3600
                insert = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
                session.execute(insert(CoachQuotaRecord).values(
                    owner_key=owner, minute_window=minute, request_count=0,
                    hour_window=hour, charged_tokens=0,
                ).on_conflict_do_nothing(index_elements=["owner_key"]))
                quota = session.scalar(select(CoachQuotaRecord).where(
                    CoachQuotaRecord.owner_key == owner).with_for_update())
                session.execute(delete(CoachQuotaLease).where(
                    CoachQuotaLease.owner_key == owner, CoachQuotaLease.expires_at <= evaluated_at))
                active = session.scalar(select(func.count()).select_from(CoachQuotaLease).where(
                    CoachQuotaLease.owner_key == owner))
                if quota.minute_window != minute:
                    quota.minute_window, quota.request_count = minute, 0
                if quota.hour_window != hour:
                    quota.hour_window, quota.charged_tokens = hour, 0
                # Fixed UTC windows; concurrency is independently bounded by leases.
                reason, retry = None, 1
                if quota.request_count >= self.config.coach_requests_per_minute:
                    reason, retry = "REQUEST_RATE", 60 - int(evaluated_at.timestamp()) % 60
                elif active >= self.config.coach_concurrent_requests:
                    reason, retry = "CONCURRENCY", 5
                elif quota.charged_tokens + self.config.max_model_tokens_per_run > self.config.coach_tokens_per_hour:
                    reason, retry = "TOKEN_QUOTA", 3600 - int(evaluated_at.timestamp()) % 3600
                if reason:
                    log_event("coach.quota.denied", reason_code=reason)
                    raise HTTPException(status_code=429, detail="Coaching limit reached. Please try again later.",
                                        headers={"Retry-After": str(retry)})
                quota.request_count += 1
                quota.charged_tokens += self.config.max_model_tokens_per_run
                # Backend timeouts bound the request; extra margin covers a model
                # call still finishing after the transport has been cancelled.
                ttl = math.ceil(self.config.ai_service_timeout_seconds +
                                self.config.ai_service_composition_timeout_seconds + 120)
                session.add(CoachQuotaLease(id=lease_id, owner_key=owner, hour_window=hour,
                    reserved_tokens=self.config.max_model_tokens_per_run,
                    expires_at=evaluated_at + timedelta(seconds=ttl)))
            log_event("coach.quota.accepted")
            return lease_id
        except SQLAlchemyError:
            log_event("coach.quota.unavailable", reason_code="QUOTA_STORE_UNAVAILABLE")
            raise HTTPException(status_code=503, detail="Coaching is temporarily unavailable.",
                                headers={"Retry-After": "5"}) from None

    def finish(self, lease_id, response=None, *, trace_id=None):
        log_event("VV entering ", "app.services.coach_quota.CoachQuota", "finish")
        actual = known_tokens(response)
        if not completed_calls(response) and not trace_id:
            # A timed-out/cancelled transport can leave AI calls running. Keep
            # their concurrency lease as well as their token reservation until
            # expiry, instead of immediately admitting replacement requests.
            log_event("coach.quota.pending", usage_complete=False)
            return
        try:
            with Session(self.engine) as session, session.begin():
                if not completed_calls(response):
                    actual = known_trace_tokens(session.get(OrchestrationTraceRecord, trace_id))
                    if actual is None:
                        log_event("coach.quota.pending", usage_complete=False)
                        return
                lease = session.get(CoachQuotaLease, lease_id)
                if lease is None:
                    return
                quota = session.scalar(select(CoachQuotaRecord).where(
                    CoachQuotaRecord.owner_key == lease.owner_key).with_for_update())
                # Re-read under the owner's lock to make repeated finishes safe.
                session.refresh(lease)
                if actual is not None and quota.hour_window == lease.hour_window:
                    quota.charged_tokens = max(0, quota.charged_tokens + actual - lease.reserved_tokens)
                session.delete(lease)
            log_event("coach.quota.completed", usage_complete=actual is not None, total_tokens=actual)
        except SQLAlchemyError:
            # Keep the reservation and lease until expiry if accounting fails.
            # Never replace a successfully committed financial outcome with an error.
            log_event("coach.quota.unavailable", reason_code="QUOTA_SETTLEMENT_FAILED")


def completed_calls(response):
    log_event("VV entering ", "app.services.coach_quota", "completed_calls")
    if response is None or response.audit.get("composition_usage_complete") is False:
        return False
    calls = response.audit.get("model_calls", [])
    if not isinstance(calls, list) or response.audit.get("model_call_count", len(calls)) != len(calls):
        return False
    return all(isinstance(call, dict) and call.get("status") == "completed" for call in calls)


def known_tokens(response):
    log_event("VV entering ", "app.services.coach_quota", "known_tokens")
    if not completed_calls(response):
        return None
    calls = response.audit.get("model_calls", [])
    total = 0
    for call in calls:
        numbers = [call.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")]
        if any(type(number) is not int or number < 0 for number in numbers) or numbers[2] != sum(numbers[:2]):
            return None
        total += numbers[2]
    return total


def known_trace_tokens(trace):
    """Settle a failed run only from paired, terminal, persisted model events."""
    if (trace is None or trace.status not in {"failed", "timed_out", "abandoned"}
            or trace.finished_at is None or not isinstance(trace.audit, dict)):
        return None
    events = trace.audit.get("durable_events")
    if not isinstance(events, list) or len(events) >= 2000:
        return None
    started, finished = set(), {}
    terminal_position = last_call_position = -1
    for position, event in enumerate(events):
        if not isinstance(event, dict):
            return None
        kind = event.get("event_type")
        if kind not in {"model.generation.started", "model.generation.finished",
                        "workflow.completed", "workflow.failed"}:
            continue
        details = event.get("details")
        if event.get("trace_id") != trace.trace_id or not isinstance(details, dict):
            return None
        if kind in {"workflow.completed", "workflow.failed"}:
            terminal_position = position
            continue
        last_call_position = position
        call_id = details.get("call_id")
        try:
            UUID(call_id)
        except (ValueError, TypeError, AttributeError):
            return None
        if kind == "model.generation.started":
            started.add(call_id)
            continue
        numbers = (details.get("input_tokens"), details.get("output_tokens"))
        if (details.get("status") != "completed" or details.get("error_code")
                or any(type(number) is not int or number < 0 for number in numbers)):
            return None
        if call_id in finished and finished[call_id] != numbers:
            return None
        finished[call_id] = numbers
    if not started or started != finished.keys() or terminal_position <= last_call_position:
        return None
    return sum(sum(numbers) for numbers in finished.values())


def purge_quota_records(session, now):
    """Drop idle pseudonymous ledgers after two days in the retention job."""
    log_event("VV entering ", "app.services.coach_quota", "purge_quota_records")
    cutoff_hour = int((now - timedelta(hours=48)).timestamp()) // 3600
    records = session.scalars(select(CoachQuotaRecord).where(
        CoachQuotaRecord.hour_window < cutoff_hour).with_for_update(skip_locked=True)).all()
    count = 0
    for record in records:
        if session.scalar(select(func.count()).select_from(CoachQuotaLease).where(
                CoachQuotaLease.owner_key == record.owner_key, CoachQuotaLease.expires_at > now)):
            continue
        # Acquire the owner's lock before deleting leases, as acquire/finish do.
        session.execute(delete(CoachQuotaLease).where(CoachQuotaLease.owner_key == record.owner_key))
        session.delete(record)
        count += 1
    log_event("coach.quota.purged", source_count=count)
    return count
