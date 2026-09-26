import re
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.clients.ai_service import AIServiceClient, AIServiceUnavailableError
from app.core.config import settings
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
    OrchestrationTraceResponse,
)
from app.infrastructure.database import get_db_session
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyOrchestrationTraceRepository,
    SQLAlchemyUserRepository,
)
from app.services.budget_alert import build_status_reply, parse_budget_status_query
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
    ai_service: Annotated[AIServiceClient, Depends(get_ai_service_client)],
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    x_synthetic_log: Annotated[str | None, Header(alias="X-Synthetic-Log")] = None,
) -> CoachResponse:
    enforce_user_access(principal, session, request.user_id)
    captured = handle_transaction_capture(session, request)
    if captured is not None:
        return _finalize_coach_response(_persist_local_coach(session, request, captured))
    query_date = parse_date_spending_query(request.message)
    if query_date is not None:
        queried = handle_date_spending_query(session, request, query_date)
        return _finalize_coach_response(_persist_local_coach(session, request, queried))
    if parse_budget_status_query(request.message):
        alert_reply = _budget_alert_reply(session, request)
        return _finalize_coach_response(_persist_local_coach(session, request, alert_reply))
    user_repository = SQLAlchemyUserRepository(session)
    persisted_snapshot = user_repository.get_financial_snapshot(request.user_id)
    log_event("coach.snapshot.loaded", snapshot_found=persisted_snapshot is not None)
    if persisted_snapshot is not None:
        request = request.model_copy(update={"snapshot": persisted_snapshot})
    try:
        response = await ai_service.coach(request)
    except AIServiceUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The coaching service is temporarily unavailable.",
        ) from error
    response.audit["response_language"] = (
        "Chinese"
        if any("\u4e00" <= character <= "\u9fff" for character in request.message)
        else "English"
    )
    with call_span("pydantic.main.BaseModel.model_validate", response_type="CoachResponse"):
        response = CoachResponse.model_validate(response.model_dump())
    _persist_coach_exchange(session, request, response)
    log_event("coach.persistence.completed", persisted=True, message_count=2)
    if (
        x_synthetic_log == "true"
        and principal.is_automation
        and automation_user_id_reserved(request.user_id)
        and settings.app_env.lower() in {"local", "test", "demo"}
    ):
        log_synthetic_exchange(request.message, response.answer)
    return _finalize_coach_response(response)


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
            if isinstance(trace_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", trace_id)
            else None
        ),
    )
    return response


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
    return OrchestrationTraceResponse(
        trace_id=record.trace_id,
        session_id=record.session_id,
        assistant_message_id=str(record.assistant_message_id),
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
    if not SQLAlchemyOrchestrationTraceRepository(session).delete_for_user(
        user_id, trace_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Orchestration trace not found",
        )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
