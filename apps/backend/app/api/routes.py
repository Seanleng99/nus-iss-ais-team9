import asyncio
import re
from datetime import UTC, date, datetime
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from coach_i18n import (
    input_pattern,
    localize_backend_text,
    localize_reviewed,
    request_locale,
    resolve_locale,
)
from coach_i18n import response_language as request_language
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clients.ai_service import AIServiceClient, AIServiceUnavailableError
from app.core.config import settings
from app.core.run_trace import active_run, record_event
from app.core.security import (
    AuthenticatedPrincipal,
    automation_user_id_reserved,
    enforce_user_access,
    require_principal,
)
from app.core.telemetry import call_span, log_event, log_synthetic_exchange, trace_method
from app.domain.schemas import (
    CoachRequest,
    CoachResponse,
    InternalCoachRequest,
    OrchestrationRunPage,
    OrchestrationRunSummary,
    OrchestrationTraceResponse,
    TraceStatus,
)
from app.domain.turn_queries import TurnQueries
from app.infrastructure.database import get_db_session
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyOrchestrationTraceRepository,
    SQLAlchemyUserRepository,
)
from app.infrastructure.run_trace import DurableRun
from app.services.budget_alert import build_status_reply
from app.services.budget_capacity import build_capacity_context
from app.services.budget_capture import handle_budget_confirmation, stage_budget_draft
from app.services.budget_planning import build_planning_context
from app.services.coach_quota import CoachQuota
from app.services.goal_capture import handle_goal_confirmation, stage_goal_draft
from app.services.privacy_guard import find_other_user_reference, other_user_data_reply
from app.services.response_composition import action_outcome, compose_backend_response
from app.services.session_context import (
    budget_query_period,
    build_session_context,
    complete_state,
    session_fact_reply,
)
from app.services.spending_query import handle_date_spending_query
from app.services.transaction_capture import _today as financial_today
from app.services.transaction_capture import handle_transaction_capture, parse_date_expression
from app.services.transaction_staging import (
    SpendingDraft,
    handle_transaction_confirmation,
    preserves_transaction_preview,
    stage_transaction_draft,
)

router = APIRouter()


def _previous_query_was_simple_day(chat):
    log_event("VV entering ", "app.api.routes", "_previous_query_was_simple_day")
    if chat is None:
        return False
    latest = next((item for item in reversed(chat.messages) if item.role == "assistant"), None)
    trace = latest.orchestration_trace if latest is not None else None
    if trace is None or trace.blocked:
        return False
    if trace.audit.get("source") == "spending_date_query":
        return True
    drafts = [item.get("data", {}).get("spending_draft") for item in trace.agent_results
              if item.get("agent") == "spending" and not item.get("blocked")]
    if len(drafts) != 1 or drafts[0] is None:
        return False
    try:
        draft = SpendingDraft.model_validate(drafts[0])
    except (TypeError, ValueError):
        return False
    return (draft.action == "query" and draft.query_date is not None
            and not draft.query_all_history and not draft.query_categories
            and draft.query_start is None and draft.query_end is None
            and draft.query_description is None and draft.query_min_amount is None
            and draft.query_max_amount is None and draft.query_group_by is None)


def _reviewed_specialist_text(result, sources):
    """Render approved evidence references before appending reviewed prose."""
    log_event("VV entering ", "app.api.routes", "_reviewed_specialist_text")
    marker = re.compile(r"\[source:([a-z0-9][a-z0-9-]{2,127})\]")
    text = result.summary.strip()
    approved = {source.source_id: source for source in sources}
    for source_id in approved:
        text = text.replace(f"[{source_id}]", f"[source:{source_id}]")
    if not set(marker.findall(text)).issubset(approved):
        return None
    if re.search(r"\[\s*source\s*:", marker.sub("", text), re.IGNORECASE):
        return None
    if re.search(r"://|\bwww\.|\]\s*\(|<\s*a\b|\b(?:href|src)\s*=", text, re.IGNORECASE):
        return None

    def reference(match):
        log_event("VV entering ", "app.api.routes", "_reviewed_specialist_text.reference")
        source = approved[match[1]]
        if not source.canonical_url.startswith("https://"):
            return ""
        label = re.sub(r"([\\`*_{}\[\]<>|])", r"\\\1", " ".join(source.title.split()))
        return f"[{label}]({quote(source.canonical_url, safe=':/?#=&%')})"

    return marker.sub(reference, text)


def is_workspace_request(message):
    log_event("VV entering ", "app.api.routes", "is_workspace_request")
    return bool(re.search(
        r"\b(schedule\w*|payday|cash.?flow|commitment\w*|protect.{0,20}categor\w*|goal contribution\w*|reconcil\w*|match.{0,30}(payment|refund|bill)|opening balance|carry.forward|rollover)\b",
        message, re.IGNORECASE,
    ))


def _current_period_start():  # pragma: no cover - trivial
    log_event("VV entering ", "app.api.routes", "_current_period_start")
    return financial_today().replace(day=1)


def _budget_alert_reply(session: Session, request: CoachRequest, *, period_missing: bool = False) -> CoachResponse:
    log_event("VV entering ", "app.api.routes", "_budget_alert_reply")
    try:
        if period_missing:
            raise ValueError("Which single month and year should I check?")
        period = budget_query_period(request) or _current_period_start()
    except ValueError as error:
        answer = str(error)
        results = [{"agent": "budget", "summary": answer, "rationale": [], "confidence": 1,
                    "data": {"needs_input": True, "questions": [answer],
                             "missing_fields": ["budget_period_start"]}}]
    else:
        answer = build_status_reply(session, request.user_id, period)
        results = []
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=[],
        answer=answer,
        agent_results=results,
        disclaimers=[],
        audit={"source": "budget_alert"},
    )


def get_ai_service_client() -> AIServiceClient:
    log_event("VV entering ", "app.api.routes", "get_ai_service_client")
    return AIServiceClient(settings)


@router.post(
    "/coach",
    response_model=CoachResponse,
)
@trace_method
async def coach(
    request: CoachRequest,
    http_response: Response,
    ai_service: Annotated[AIServiceClient, Depends(get_ai_service_client)],
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    x_synthetic_log: Annotated[str | None, Header(alias="X-Synthetic-Log")] = None,
) -> CoachResponse:
    # Authorize both profile and conversation before creating any audit record.
    log_event("VV entering ", "app.api.routes", "coach")
    enforce_user_access(principal, session, request.user_id)
    repository = SQLAlchemyChatRepository(session)
    try:
        context_snapshot = repository.context_snapshot(request.user_id, request.session_id)
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error
    quota = CoachQuota(session.get_bind(), settings)
    lease = quota.acquire(principal)
    response = None
    usage_trace = {}
    try:
        response = await _execute_coach(request, http_response, ai_service, session, principal,
                                        x_synthetic_log, context_snapshot, usage_trace)
        return response
    finally:
        if response is None:
            session.rollback()
        quota.finish(lease, response, trace_id=usage_trace.get("trace_id"))


async def _execute_coach(request, http_response, ai_service, session, principal, x_synthetic_log, context_snapshot, usage_trace):
    log_event("VV entering ", "app.api.routes", "_execute_coach")
    repository = SQLAlchemyChatRepository(session)
    existed, revision, context = context_snapshot
    chat = repository.get_for_update(request.user_id, request.session_id)
    if chat is None:
        if existed or repository.id_exists(request.session_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        try:
            chat = repository.create(request.user_id, request.session_id, request.message[:120])
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(status_code=409, detail="Conversation changed; please retry.") from error
    elif len(chat.messages) != revision:
        raise HTTPException(status_code=409, detail="Conversation changed; please retry.")
    run = DurableRun(session, chat.id, settings.ai_service_timeout_seconds + settings.ai_service_composition_timeout_seconds)
    usage_trace["trace_id"] = run.trace_id
    token = active_run.set(run)
    try:
        record_event("backend.authorization.accepted", authenticated=True)
        run.buffered = True
        response = await _coach(request, http_response, ai_service, session, principal, x_synthetic_log,
                                (existed, revision, context))
        http_response.headers["X-Trace-ID"] = run.trace_id
        return response
    except asyncio.CancelledError:
        run.fail("abandoned", "REQUEST_CANCELLED")
        raise
    except Exception as error:
        if not run.closed:
            run.fail("failed", "RESPONSE_PERSISTENCE_FAILED")
        if isinstance(error, HTTPException):
            error.headers = {**(error.headers or {}), "X-Trace-ID": run.trace_id}
        raise
    finally:
        active_run.reset(token)


async def _coach(request, http_response, ai_service, session, principal, x_synthetic_log, context_snapshot):
    log_event("VV entering ", "app.api.routes", "_coach")
    chat_repository = SQLAlchemyChatRepository(session)
    conversation_existed, revision, context = context_snapshot
    user_repository = SQLAlchemyUserRepository(session)
    profile = user_repository.get_profile(request.user_id)
    locale = resolve_locale(
        request.message, selected=request.response_locale,
        preferred=(profile.preferred_language if profile is not None else
                   request.snapshot.preferences.get("preferred_language")), history=context,
    )
    request = request.model_copy(update={"response_locale": locale})
    # Refuse third-party data requests before any local handler can answer from this user's data.
    if find_other_user_reference(request.message, request.user_id) is not None:
        record_event("backend.handler.selected", handler="privacy_guard", reason_code="CROSS_USER_REFERENCE")
        return _finalize_coach_response(
            _persist_local_coach(session, request, other_user_data_reply(request.session_id))
        )
    existing_chat = chat_repository.get(request.user_id, request.session_id)
    request = InternalCoachRequest(
        **request.model_dump(), conversation_context=context,
        message_position=revision + 1,
        session_context=build_session_context(existing_chat, request.message, revision + 1),
    )
    persisted_snapshot = user_repository.get_financial_snapshot(request.user_id, request.budget_period_start)
    selected_spending_period = (date.fromisoformat(persisted_snapshot.period_start)
                               if persisted_snapshot and persisted_snapshot.period_start else request.budget_period_start)
    if persisted_snapshot is not None:
        request = request.model_copy(update={"snapshot": persisted_snapshot})
    confirmed_goal = handle_goal_confirmation(session, request)
    if confirmed_goal is not None:
        record_event("backend.handler.selected", handler="goal_confirmation")
        return _finalize_coach_response(_persist_local_coach(session, request,
            await compose_backend_response(ai_service, request, confirmed_goal)))
    confirmed = handle_budget_confirmation(session, request)
    if confirmed is not None:
        record_event("backend.handler.selected", handler="budget_confirmation")
        return _finalize_coach_response(_persist_local_coach(session, request,
            await compose_backend_response(ai_service, request, confirmed)))
    confirmed_transaction = handle_transaction_confirmation(session, request)
    if confirmed_transaction is not None:
        record_event("backend.handler.selected", handler="transaction_confirmation")
        return _finalize_coach_response(
            _persist_local_coach(session, request,
                await compose_backend_response(ai_service, request, confirmed_transaction))
        )
    if existing_chat and existing_chat.pending_goal:
        existing_chat.pending_goal = {**existing_chat.pending_goal, "ready": False}
    pending_goal = existing_chat.pending_goal if existing_chat else None
    pending_budget = existing_chat.pending_budget if existing_chat else None
    pending_transaction = existing_chat.pending_transaction if existing_chat else None
    goal_context = pending_goal is not None or bool(
        re.search(input_pattern("backend.api.routes.goal_context"), request.message, re.IGNORECASE)
    )
    stated_financial_detail = any(
        fact["source_position"] == revision + 1
        for fact in request.session_context["facts"].values()
    )
    # Drafts and explicit financial facts take precedence over transaction edits.
    captured = (
        None if goal_context or pending_budget or stated_financial_detail or "budget" in request.message.casefold() or is_workspace_request(request.message)
        else handle_transaction_capture(session, request)
    )
    if captured is not None:
        record_event("backend.handler.selected", handler="transaction_capture")
        return _finalize_coach_response(_persist_local_coach(session, request,
            await compose_backend_response(ai_service, request, captured)))
    # Only a complete, bare date expression can use the existing spending
    # subject. Filters, ranges and additional intents go to semantic extraction.
    followup = re.fullmatch(r"(?:what|how)\s+about\s+(.+?)[?!.]*", request.message.strip(), re.IGNORECASE)
    query_date = (parse_date_expression(followup[1], allow_future=True)
                  if followup and request.session_context["active_topic"] == "spending"
                  and _previous_query_was_simple_day(existing_chat) else None)
    if query_date is not None and not any((pending_budget, pending_goal, pending_transaction)):
        record_event("backend.handler.selected", handler="date_spending_query")
        return _finalize_coach_response(_persist_local_coach(
            session, request, await compose_backend_response(ai_service, request,
                handle_date_spending_query(session, request, query_date))
        ))
    log_event("coach.snapshot.loaded", snapshot_found=persisted_snapshot is not None)
    if persisted_snapshot is not None:
        request = request.model_copy(update={"snapshot": persisted_snapshot})
    request = request.model_copy(update={
        "pending_goal": pending_goal["draft"] if pending_goal else None,
        "pending_budget": pending_budget["draft"] if pending_budget else None,
        "pending_transaction": pending_transaction["draft"] if pending_transaction else None,
        "budget_context": build_planning_context(
            session, request.user_id, message=request.message,
            pending=pending_budget["draft"] if pending_budget else None,
            period=request.budget_period_start,
        ),
        "saved_budget_capacity": build_capacity_context(session, request.user_id, request.budget_period_start),
    })
    log_event("coach.history.loaded", history_count=len(context))
    session.rollback()
    chat_session = chat_repository.get_for_update(request.user_id, request.session_id)
    if chat_session is None:
        if conversation_existed or chat_repository.id_exists(request.session_id):
            raise HTTPException(status_code=404, detail="Conversation not found")
        try:
            chat_session = chat_repository.create(
                request.user_id, request.session_id, request.message[:120]
            )
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(status_code=409, detail="Conversation changed; please retry.") from error
    elif len(chat_session.messages) != revision:
        raise HTTPException(status_code=409, detail="Conversation changed; please retry.")
    if chat_session.pending_goal:
        chat_session.pending_goal = {**chat_session.pending_goal, "ready": False}
    if chat_session.pending_budget:
        chat_session.pending_budget = {**chat_session.pending_budget, "ready": False}
    if (chat_session.pending_transaction
            and not preserves_transaction_preview(chat_session.pending_transaction)):
        chat_session.pending_transaction = {
            **chat_session.pending_transaction,
            "ready": False,
        }
    # DurableRun commits metadata and releases the conversation lock before AI.
    run = active_run.get()
    run.flush()
    record_event("backend.handler.selected", handler="agent_orchestrator")
    try:
        response = await ai_service.coach(request)
        response.audit["trace_id"] = run.trace_id
        response.audit["response_language"] = request_language(request)
        response.audit["response_locale"] = request_locale(request)
        with call_span("pydantic.main.BaseModel.model_validate", response_type="CoachResponse"):
            response = CoachResponse.model_validate(response.model_dump())
        run.buffered = True
        # Reacquire the conversation lock after incremental event commits.
        session.expire_all()
        enforce_user_access(principal, session, request.user_id)
        chat_session = chat_repository.get_for_update(request.user_id, request.session_id)
        if chat_session is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if len(chat_session.messages) != revision:
            raise HTTPException(status_code=409, detail="Conversation changed; please retry.")
        outcomes = []
        if not response.blocked:
            try:
                queries = TurnQueries.model_validate(response.audit.get("turn_decision", {}))
            except (TypeError, ValueError):
                queries = TurnQueries()
            if queries.budget_status_query:
                from coach_math.budget_scope import resolve_budget_periods
                scope = queries.budget_scope
                periods = resolve_budget_periods(scope, request.budget_period_start) if scope and scope.kind not in {"default", "all"} else []
                query_request = request.model_copy(update={
                    "budget_period_start": periods[0] if len(periods) == 1 else queries.budget_status_period_start or request.budget_period_start,
                })
                if scope and (scope.kind == "all" or len(periods) > 1) and not queries.budget_scope_unclear:
                    from app.services.budget_records import (
                        build_record_change,
                        describe_record_change,
                    )
                    target, details = build_record_change(session, request.user_id,
                        {"action": "compare", "scope": scope.model_dump(mode="json")})
                    alert_reply = CoachResponse(session_id=request.session_id, selected_agents=["budget"],
                        answer=describe_record_change(target, details, locale=request_locale(request)),
                        agent_results=[], disclaimers=[], audit={"source": "budget_records", "action_status": "read_only"})
                else:
                    alert_reply = _budget_alert_reply(
                        session, query_request, period_missing=queries.budget_scope_unclear or "budget_period_start" in queries.missing_fields,
                    )
                outcomes.append(action_outcome("budget_status", alert_reply))
                if alert_reply.agent_results:
                    response.agent_results.extend(alert_reply.agent_results)
                    turn = response.audit.setdefault("turn_decision", {})
                    turn["missing_fields"] = list(dict.fromkeys([
                        *turn.get("missing_fields", []), "budget_period_start",
                    ]))
            if queries.memory_question:
                state = complete_state(request.session_context, response, request.message, revision + 1)
                recall_request = request.model_copy(update={"session_context": state or request.session_context})
                recalled = session_fact_reply(recall_request, semantic=True, fields=queries.memory_fields or None)
                if recalled is not None:
                    outcomes.append(action_outcome("session_recall", recalled))
        for operation, stage in (
            ("budget", lambda: stage_budget_draft(session, request.user_id, chat_session, response,
                                                 default_period=request.budget_period_start)),
            ("goal", lambda: stage_goal_draft(session, request.user_id, chat_session, response)),
            ("spending", lambda: stage_transaction_draft(
                session, request.user_id, chat_session, response, request.message,
                selected_period_start=selected_spending_period)),
        ):
            before = response.answer
            previous_status = response.audit.pop("action_status", None)
            stage()
            record_event("backend.action.outcome", phase="pending_commit", operation=operation,
                         action_status=response.audit.get("action_status", response.audit.get(f"{operation}_capture", "reviewed_result")),
                         blocked=response.blocked)
            if response.answer != before and not response.blocked:
                outcomes.append(action_outcome(operation, response))
            elif previous_status is not None:
                response.audit["action_status"] = previous_status
        if outcomes and not response.blocked:
            # Action outcomes must come from authenticated writes/reads. Keep
            # independently validated specialist answers for other turn intents.
            action_answer = "\n\n".join(dict.fromkeys(
                localize_backend_text(item["text"], request_locale(request)) for item in outcomes))
            independent = [_reviewed_specialist_text(item, response.sources) for item in response.agent_results
                if not item.blocked and item.agent.value != "risk_compliance"
                and not any(key in item.data for key in ("budget_draft", "goal_draft", "spending_draft"))
                and item.summary.strip() and item.summary.strip() != action_answer.strip()]
            response.answer = "\n\n".join([action_answer, *dict.fromkeys(text for text in independent if text)])
            response.audit["reviewed_action_outcome"] = True
            response = await compose_backend_response(ai_service, request, response, outcomes)
        if chat_session.pending_budget and not any("goal_draft" in r.data for r in response.agent_results):
            chat_session.pending_goal = None
        chat_repository.append_message(chat_session, "user", request.message)
        next_state = complete_state(request.session_context, response, request.message, revision + 1)
        if next_state is not None:
            chat_session.conversation_state = next_state
        assistant_message = chat_repository.append_message(
            chat_session,
            "assistant",
            response.answer,
            [source.model_dump() for source in response.sources],
        )
        run.complete(response, assistant_message.id)
        log_event("coach.persistence.completed", persisted=True, message_count=2)
        if (
            x_synthetic_log == "true"
            and principal.is_automation
            and automation_user_id_reserved(request.user_id)
            and settings.app_env.lower() in {"local", "test", "demo"}
        ):
            log_synthetic_exchange(request.message, response.answer)
        http_response.headers["X-Trace-ID"] = run.trace_id
        return _finalize_coach_response(response)
    except AIServiceUnavailableError as error:
        if error.timed_out:
            run.record_event("backend.ai.timeout", component=error.timeout_origin or "unknown")
        run.fail(
            "timed_out" if error.timed_out else "failed",
            "AI_SERVICE_TIMEOUT" if error.timed_out else "AI_SERVICE_UNAVAILABLE",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The coaching service is temporarily unavailable.",
            headers={"X-Trace-ID": run.trace_id},
        ) from error
    except asyncio.CancelledError:
        run.fail("abandoned", "REQUEST_CANCELLED")
        raise
    except Exception:
        run.fail("failed", "RESPONSE_PERSISTENCE_FAILED")
        raise


@trace_method
def _persist_local_coach(
    session: Session, request: CoachRequest, response: CoachResponse
) -> CoachResponse:
    log_event("VV entering ", "app.api.routes", "_persist_local_coach")
    locale = request_locale(request)
    response.audit.update(response_locale=locale, response_language=request_language(request))
    record_event("backend.action.outcome", phase="pending_commit", handler=str(response.audit.get("source", "local_handler")),
                 action_status=response.audit.get("action_status", "reviewed_result"), blocked=response.blocked)
    response.audit["reviewed_response"] = True
    response.audit.setdefault("response_provenance", "backend_validated_local")
    response.answer = localize_backend_text(response.answer, locale)
    for result in response.agent_results:
        result.summary = localize_reviewed(result.summary, locale)
        result.rationale = [localize_reviewed(text, locale) for text in result.rationale]
    response.disclaimers = [localize_reviewed(text, locale) for text in response.disclaimers]
    response = CoachResponse.model_validate(response.model_dump())
    _persist_coach_exchange(session, request, response)
    log_event("coach.persistence.completed", persisted=True, message_count=2)
    return response


@trace_method
def _persist_coach_exchange(
    session: Session, request: CoachRequest, response: CoachResponse
) -> None:
    log_event("VV entering ", "app.api.routes", "_persist_coach_exchange")
    chat_repository = SQLAlchemyChatRepository(session)
    chat_session = chat_repository.get_for_update(request.user_id, request.session_id)
    if chat_session is None:
        if chat_repository.id_exists(request.session_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        chat_session = chat_repository.create(
            request.user_id, request.session_id, request.message[:120]
        )
    state = build_session_context(chat_session, request.message, len(chat_session.messages) + 1)
    chat_repository.append_message(chat_session, "user", request.message)
    next_state = complete_state(state, response, request.message, len(chat_session.messages))
    if next_state is not None:
        chat_session.conversation_state = next_state
    assistant_message = chat_repository.append_message(
        chat_session,
        "assistant",
        response.answer,
        [source.model_dump() for source in response.sources],
    )
    run = active_run.get()
    if run is not None:
        run.complete(response, assistant_message.id)
        return
    trace_id = str(response.audit.get("trace_id", "")).strip() or str(uuid4())
    response.audit["trace_id"] = trace_id
    if trace_id:
        SQLAlchemyOrchestrationTraceRepository(session).create(
            trace_id=trace_id,
            session_id=chat_session.id,
            assistant_message_id=assistant_message.id,
            selected_agents=[agent.value for agent in response.selected_agents],
            agent_results=[item.model_dump(mode="json") for item in response.agent_results],
            audit=response.audit,
            blocked=response.blocked,
        )
    with call_span("sqlalchemy.orm.session.Session.commit"):
        session.commit()


@trace_method
def _finalize_coach_response(response: CoachResponse) -> CoachResponse:
    log_event("VV entering ", "app.api.routes", "_finalize_coach_response")
    trace_id = response.audit.get("trace_id")
    log_event(
        "coach.response.ready",
        selected_agents=[agent.value for agent in response.selected_agents],
        blocked=response.blocked,
        source_count=len(response.sources),
        response_fields=list(CoachResponse.model_fields),
        output_characters=len(response.answer),
        trace_id=(
            trace_id
            if isinstance(trace_id, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", trace_id)
            else None
        ),
    )
    return response


@router.get("/coach/traces", response_model=OrchestrationRunPage)
def list_orchestration_traces(
    user_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    status: TraceStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrchestrationRunPage:
    log_event("VV entering ", "app.api.routes", "list_orchestration_traces")
    enforce_user_access(principal, session, user_id)
    repository = SQLAlchemyOrchestrationTraceRepository(session)
    repository.mark_abandoned(datetime.now(UTC), user_id=user_id)
    session.commit()
    rows = repository.list_for_user(user_id, status=status, limit=limit, offset=offset)
    return OrchestrationRunPage(
        items=[
            OrchestrationRunSummary(
                trace_id=record.trace_id,
                session_id=record.session_id,
                conversation_title=title,
                status=record.status,
                selected_agents=record.selected_agents,
                created_at=record.created_at,
                finished_at=record.finished_at,
                error_code=record.error_code,
            )
            for record, title in rows[:limit]
        ],
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.get(
    "/coach/traces/{trace_id}",
    response_model=OrchestrationTraceResponse,
)
def get_orchestration_trace(
    trace_id: str,
    user_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> OrchestrationTraceResponse:
    log_event("VV entering ", "app.api.routes", "get_orchestration_trace")
    enforce_user_access(principal, session, user_id)
    record = SQLAlchemyOrchestrationTraceRepository(session).get_for_user(
        user_id,
        trace_id,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Orchestration trace not found",
        )
    if record.status == "running" and record.deadline_at is not None:
        deadline = (
            record.deadline_at.replace(tzinfo=UTC)
            if record.deadline_at.tzinfo is None
            else record.deadline_at
        )
        if deadline < datetime.now(UTC):
            SQLAlchemyOrchestrationTraceRepository(session).mark_abandoned(
                datetime.now(UTC), user_id=user_id
            )
            session.commit()
            session.refresh(record)
    return OrchestrationTraceResponse(
        status=record.status,
        correlation_id=record.correlation_id,
        finished_at=record.finished_at,
        error_code=record.error_code,
        trace_id=record.trace_id,
        session_id=record.session_id,
        assistant_message_id=str(record.assistant_message_id)
        if record.assistant_message_id
        else None,
        selected_agents=record.selected_agents,
        agent_results=record.agent_results,
        audit=record.audit,
        blocked=record.blocked,
        model_provider=record.model_provider,
        model_id=record.model_id,
        prompt_set_version=record.prompt_set_version,
        created_at=record.created_at,
    )


@router.delete(
    "/coach/traces/{trace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_orchestration_trace(
    trace_id: str,
    user_id: str,
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> Response:
    log_event("VV entering ", "app.api.routes", "delete_orchestration_trace")
    enforce_user_access(principal, session, user_id)
    if not SQLAlchemyOrchestrationTraceRepository(session).delete_for_user(user_id, trace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Orchestration trace not found",
        )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
