"""Versioned, content-free trace contract shared by producers, storage and viewers.

Unknown fields and invalid values are discarded at every trust boundary. Never add
prompts, answers, quotes, exception messages or unreviewed rationale to this contract.
"""

import re
from datetime import UTC, datetime
from math import isfinite
from uuid import UUID, uuid4

from coach_trace.review import POLICY_CLAUSES, VALIDATION_REASONS, review_metadata

SCHEMA_VERSION = 1
CODE = re.compile(r"^[A-Za-z0-9_./:@{}<>-]{1,180}$")
COUNTS = {
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
    "attempts",
    "top_k",
    "history_count",
    "message_count",
    "model_call_count",
    "timeout_seconds",
    "response_bytes",
    "question_characters",
    "question_count",
    "model_input_tokens",
    "model_output_tokens",
    "policy_note_count",
    "policy_source_count",
    "retrieval_source_count",
    "queue_duration_ms",
    "execution_duration_ms",
    "dependency_wait_ms",
    "backoff_duration_ms",
    "max_output_tokens",
    "review_round",
    "repair_round",
    "used_tokens",
    "estimated_repair_tokens",
    "token_limit",
    "remaining_tokens",
    "source_quote_count",
}
FLAGS = {
    "blocked",
    "allowed",
    "cache_hit",
    "snapshot_found",
    "authenticated",
    "persisted",
    "required",
    "retryable",
    "goal_capture",
    "budget_capture",
    "budget_planning",
    "spending_capture",
    "answer_complete",
    "repairable",
    "request_allowed",
    "financial_language_safe",
    "composition_usage_complete",
    "requires_spending",
    "requires_income",
    "requires_capacity",
}
CODES = {
    "estimate_basis",
    "source",
    "category",
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
    "prompt_content_hash",
    "build_commit",
    "corpus_version",
    "knowledge_base_id",
    "http_method",
    "route",
    "trace_id",
    "request_id",
    "task_id",
    "call_id",
    "event_id",
    "capability",
    "policy_corpus_version",
    "requested_by",
    "resolution",
    "retrieval_consumer",
    "input_fingerprint",
    "model_provider",
    "decision_source",
    "rule_id",
    "decision_id",
    "parent_decision_id",
    "requester_task_id",
    "provider_task_id",
    "question_id",
    "coverage_status",
    "passage_id",
    "source_id",
    "handler",
    "operation",
    "action_status",
    "phase",
    "execution_id",
    "generation_id",
    "correction_of_call_id",
    "validation_status",
    "reasoning_effort",
}
CODE_LISTS = {
    "selected_agents",
    "response_fields",
    "source_ids",
    "block_reasons",
    "review_block_categories",
    "capabilities",
    "policy_corpus_versions",
    "retrieval_consumers",
    "retrieval_corpus_versions",
    "evidence_refs",
    "missing_fields",
    "passage_ids",
    "repair_blockers",
}
DECISION_FIELDS = {
    "budget_scope", "spending_scope", "spending_analysis_period", "budget_scope_unclear", "spending_scope_unclear",
    "selected_agents",
    "query_topics",
    "routing_mode",
    "budget_status_query",
    "budget_capacity_query",
    "memory_question",
    "goal_capture",
    "budget_capture",
    "budget_planning",
    "spending_capture",
}


def code(value):
    return value if isinstance(value, str) and CODE.fullmatch(value) else None


def topic_ids(values):
    # Only governed public topic names may cross the incremental boundary.
    from coach_i18n import load_data

    vocabulary = load_data("education_vocabulary")
    topics = {topic for _, topic in vocabulary["EDUCATION_TOPIC_PHRASES"]}
    topics.update(topic for topic, _ in vocabulary["EDUCATION_DETAIL_PHRASES"])
    topics.update({"investment basics", "general investment concepts"})
    canonical = {topic.replace(" ", "_"): topic for topic in topics}
    return list(
        dict.fromkeys(
            value.replace(" ", "_")
            for value in values[:30]
            if isinstance(value, str) and (value in topics or value in canonical)
        )
    )


def safe_details(details, *, decision=False):
    if not isinstance(details, dict):
        return {}
    result = {}
    for key, value in details.items():
        if decision and key not in DECISION_FIELDS:
            continue
        if key in {"block_reasons", "review_block_categories"}:
            if isinstance(value, (list, tuple)):
                result[key] = review_metadata({key: value})[key]
            continue
        if key == "validation_reason":
            if isinstance(value, str) and value in VALIDATION_REASONS:
                result[key] = value
            continue
        if key == "policy_clause_refs":
            if isinstance(value, (list, tuple)):
                result[key] = list(dict.fromkeys(
                    item for item in value[:20] if isinstance(item, str) and item in POLICY_CLAUSES
                ))
            continue
        if key == "task_assignments" and isinstance(value, (list, tuple)):
            result[key] = [
                {"agent": item["agent"], **{
                    flag: item[flag] for flag in ("requires_spending", "requires_income", "requires_capacity")
                    if type(item.get(flag)) is bool
                }, **{field: item[field] for field, allowed in (
                    ("operation", {"analysis", "reconciliation", "forecast", "record_read", "planning", "record_change"}),
                    ("goal_mode", {"standard", "emergency_reserve"}))
                    if isinstance(item.get(field), str) and item[field] in allowed}
                } for item in value[:4] if isinstance(item, dict)
                and item.get("agent") in {"spending", "budget", "goal_strategy", "investment_education"}
            ]
            continue
        if key == "review_issues" and isinstance(value, (list, tuple)):
            result[key] = []
            for item in value[:6]:
                if (not isinstance(item, dict) or not re.fullmatch(r"review_[1-6]", str(item.get("issue_id", "")))
                        or item.get("owner") not in {"spending", "budget", "goal_strategy", "investment_education", "composition"}
                        or not re.fullmatch(r"draft|request|spending|budget|goal_strategy|investment_education|education_[1-9][0-9]*", str(item.get("section_id", "")))
                        or item.get("action") not in {"qualify", "ground_claim", "remove_claim", "complete"}
                        or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("requirement_hash", "")))):
                    continue
                issue = {field: item[field] for field in ("issue_id", "section_id", "owner", "action", "requirement_hash")}
                if item.get("category") in {"prohibited_request", "personal_advice", "return_guarantee", "privacy",
                                           "injection", "citation_attribution", "factual_qualification", "unverifiable_claim"}:
                    issue["category"] = item["category"]
                refs = item.get("evidence_refs", [])
                issue["evidence_refs"] = [ref for ref in (refs[:6] if isinstance(refs, (list, tuple)) else [])
                    if isinstance(ref, str) and re.fullmatch(r"(?:spending|budget|goal_strategy)\.[a-z_]{1,64}", ref)]
                if (type(item.get("claim_start")) is int and type(item.get("claim_end")) is int
                        and 0 <= item["claim_start"] < item["claim_end"] <= 6000):
                    issue.update(claim_start=item["claim_start"], claim_end=item["claim_end"])
                result[key].append(issue)
            continue
        if key in {"budget_scope", "spending_scope"} and isinstance(value, dict):
            from coach_math.budget_scope import BudgetScope
            try:
                result[key] = BudgetScope.model_validate(value).model_dump(mode="json", exclude_none=True)
            except ValueError:
                pass
            continue
        if key == "spending_analysis_period" and isinstance(value, str):
            from datetime import date
            try:
                parsed = date.fromisoformat(value)
                if parsed.day == 1:
                    result[key] = parsed.isoformat()
            except ValueError:
                pass
            continue
        if key in {"budget_scope_unclear", "spending_scope_unclear"} and type(value) is bool:
            result[key] = value
            continue
        if (
            key in COUNTS
            and type(value) in (int, float)
            and isfinite(value)
            and value >= 0
            or (key in FLAGS or key in {"budget_status_query", "budget_capacity_query", "memory_question"})
            and type(value) is bool
        ):
            result[key] = value
        elif (
            key in {"error_code", "reason_code"}
            and not code(value)
            and value is not None
        ):
            result[key] = "UNSAFE_VALUE_REDACTED"
        elif key in CODES and code(value):
            result[key] = value
        elif key in CODE_LISTS and isinstance(value, (list, tuple)):
            result[key] = [item for item in value[:30] if code(item)]
        elif key == "query_topics" and isinstance(value, (list, tuple)):
            result[key] = topic_ids(value)
        elif key in {"before", "after"} and not decision and isinstance(value, dict):
            result[key] = safe_details(value, decision=True)
    return result


def safe_event(event, trace_id):
    if not isinstance(event, dict) or event.get("trace_id") != trace_id:
        raise ValueError("Invalid trace event")
    version = event.get("schema_version", SCHEMA_VERSION)  # legacy frames
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError("Unsupported trace schema")
    event_type = code(event.get("event_type"))
    if not event_type:
        raise ValueError("Invalid event type")
    stamp = datetime.fromisoformat(event.get("timestamp") or event["occurred_at"])
    if stamp.tzinfo is None:
        raise ValueError("Missing event timezone")
    result = {
        "schema_version": version,
        "event_id": str(UUID(event["event_id"])),
        "trace_id": trace_id,
        "event_type": event_type,
        "timestamp": stamp.isoformat(),
    }
    for key in (
        "task_id",
        "parent_task_id",
        "span_id",
        "parent_span_id",
        "actor",
        "correlation_id",
    ):
        if code(event.get(key)):
            result[key] = event[key]
    result["details"] = safe_details(event.get("details", {}))
    if type(event.get("attempt")) is int and event["attempt"] >= 1:
        result["details"]["attempt"] = event["attempt"]
    return result


def make_event(event_type, trace_id, *, actor=None, details=None, **context):
    return safe_event(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(uuid4()),
            "trace_id": trace_id,
            "event_type": event_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "actor": actor,
            "details": details or {},
            **context,
        },
        trace_id,
    )


# Explicit semantic allowlist: routine method/HTTP logs do not flood the audit store.
SEMANTIC_EVENTS = {
    "synthesis.strategy",
    "model.response.parsed",
    "model.contract.validated",
    "model.contract.rejected",
    "model.decision.accepted",
    "model.decision.rejected",
    "model.correction.requested",
    "agent.guardrail",
    "agent.input.guardrail",
    "agent.output.guardrail",
    "agent.guardrail.evaluated",
    "agent.output.evaluated",
    "agent.grounding.ready",
    "agent.grounding",
    "agent.evidence_gap",
    "education.coverage.assessed",
    "education.answerability.rejected",
    "education.answer.provenance",
    "education.grounding.reused",
    "education.question.coverage",
    "composition.started",
    "composition.completed",
    "composition.fallback",
}


def is_durable_event(event_type):
    return event_type.startswith("model.generation.") or event_type in SEMANTIC_EVENTS
