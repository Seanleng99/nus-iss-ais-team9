import asyncio
import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.clients.ai_service import AIServiceClient, AIServiceUnavailableError
from app.core.config import settings
from app.core.run_trace import active_run
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
from app.infrastructure.database import get_db_session
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyOrchestrationTraceRepository,
    SQLAlchemyUserRepository,
)
from app.infrastructure.run_trace import DurableRun
from app.services.budget_alert import build_status_reply, parse_budget_status_query
from app.services.budget_capacity import build_capacity_context
from app.services.budget_capture import handle_budget_confirmation, stage_budget_draft
from app.services.budget_planning import build_planning_context
from app.services.goal_capture import handle_goal_confirmation, stage_goal_draft
from app.services.privacy_guard import find_other_user_reference, other_user_data_reply
from app.services.recurring_forecast import (
    handle_recurring_forecast_query,
    parse_recurring_forecast_query,
)
from app.services.spending_query import handle_date_spending_query, parse_date_spending_query
from app.services.transaction_capture import handle_transaction_capture

router = APIRouter()


def _current_period_start():  # pragma: no cover - trivial
    return datetime.now(UTC).date().replace(day=1)


def _budget_alert_reply(session: Session, request: CoachRequest) -> CoachResponse:
    answer = build_status_reply(session, request.user_id, _current_period_start())
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=[],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit={"source": "budget_alert"},
    )


def get_ai_service_client() -> AIServiceClient:
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
    enforce_user_access(principal, session, request.user_id)
    chat_repository = SQLAlchemyChatRepository(session)
    try:
        conversation_existed, revision, context = chat_repository.context_snapshot(
            request.user_id, request.session_id
        )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error
    # Refuse third-party data requests before any local handler can answer from this user's data.
    if find_other_user_reference(request.message, request.user_id) is not None:
        return _finalize_coach_response(
            _persist_local_coach(session, request, other_user_data_reply(request.session_id))
        )
    confirmed_goal = handle_goal_confirmation(session, request)
    if confirmed_goal is not None:
        return _finalize_coach_response(_persist_local_coach(session, request, confirmed_goal))
    confirmed = handle_budget_confirmation(session, request)
    if confirmed is not None:
        return _finalize_coach_response(_persist_local_coach(session, request, confirmed))
    existing_chat = chat_repository.get(request.user_id, request.session_id)
    if existing_chat and existing_chat.pending_goal:
        existing_chat.pending_goal = {**existing_chat.pending_goal, "ready": False}
    pending_goal = existing_chat.pending_goal if existing_chat else None
    pending_budget = existing_chat.pending_budget if existing_chat else None
    goal_context = pending_goal is not None or bool(
        re.search(r"\bgoals?\b|目标", request.message, re.IGNORECASE)
    )
    # Goal and budget drafts take precedence over transaction/date parsing for follow-ups.
    captured = (
        None if goal_context or pending_budget or "budget" in request.message.casefold()
        else handle_transaction_capture(session, request)
    )
    if captured is not None:
        return _finalize_coach_response(_persist_local_coach(session, request, captured))
    query_date = parse_date_spending_query(request.message)
    if query_date is not None and not pending_budget and not pending_goal:
        queried = handle_date_spending_query(session, request, query_date)
        return _finalize_coach_response(_persist_local_coach(session, request, queried))
    if not pending_budget and not goal_context and parse_recurring_forecast_query(request.message):
        forecast = handle_recurring_forecast_query(session, request.user_id, request.session_id)
        return _finalize_coach_response(_persist_local_coach(session, request, forecast))
    if not pending_budget and not pending_goal and parse_budget_status_query(request.message):
        alert_reply = _budget_alert_reply(session, request)
        return _finalize_coach_response(_persist_local_coach(session, request, alert_reply))
    user_repository = SQLAlchemyUserRepository(session)
    persisted_snapshot = user_repository.get_financial_snapshot(request.user_id)
    log_event("coach.snapshot.loaded", snapshot_found=persisted_snapshot is not None)
    if persisted_snapshot is not None:
        request = request.model_copy(update={"snapshot": persisted_snapshot})
    request = InternalCoachRequest(
        **request.model_dump(), conversation_context=context,
        pending_goal=pending_goal["draft"] if pending_goal else None,
        pending_budget=pending_budget["draft"] if pending_budget else None,
        budget_context=build_planning_context(session, request.user_id),
        saved_budget_capacity=build_capacity_context(session, request.user_id, request.budget_period_start),
    )
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
    # DurableRun commits metadata and releases the conversation lock before AI.
    run = DurableRun(session, chat_session.id, settings.ai_service_timeout_seconds)
    token = active_run.set(run)
    try:
        response = await ai_service.coach(request)
        response.audit["trace_id"] = run.trace_id
        response.audit["response_language"] = (
            "Chinese"
            if any("\u4e00" <= character <= "\u9fff" for character in request.message)
            else "English"
        )
        with call_span("pydantic.main.BaseModel.model_validate", response_type="CoachResponse"):
            response = CoachResponse.model_validate(response.model_dump())
        # Reacquire the conversation lock after incremental event commits.
        session.expire_all()
        enforce_user_access(principal, session, request.user_id)
        chat_session = chat_repository.get_for_update(request.user_id, request.session_id)
        if chat_session is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if len(chat_session.messages) != revision:
            raise HTTPException(status_code=409, detail="Conversation changed; please retry.")
        stage_budget_draft(session, request.user_id, chat_session, response)
        stage_goal_draft(session, request.user_id, chat_session, response)
        if chat_session.pending_budget and not any("goal_draft" in r.data for r in response.agent_results):
            chat_session.pending_goal = None
        chat_repository.append_message(chat_session, "user", request.message)
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
    finally:
        active_run.reset(token)


@trace_method
def _persist_local_coach(
    session: Session, request: CoachRequest, response: CoachResponse
) -> CoachResponse:
    _persist_coach_exchange(session, request, response)
    log_event("coach.persistence.completed", persisted=True, message_count=2)
    return response


@trace_method
def _persist_coach_exchange(
    session: Session, request: CoachRequest, response: CoachResponse
) -> None:
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
    chat_repository.append_message(chat_session, "user", request.message)
    assistant_message = chat_repository.append_message(
        chat_session,
        "assistant",
        response.answer,
        [source.model_dump() for source in response.sources],
    )
    trace_id = str(response.audit.get("trace_id", "")).strip()
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
    enforce_user_access(principal, session, user_id)
    if not SQLAlchemyOrchestrationTraceRepository(session).delete_for_user(user_id, trace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Orchestration trace not found",
        )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
