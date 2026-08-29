from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.clients.ai_service import AIServiceClient, AIServiceUnavailableError
from app.core.config import settings
from app.core.security import (
    AuthenticatedPrincipal,
    enforce_user_access,
    require_principal,
)
from app.domain.schemas import CoachRequest, CoachResponse, OrchestrationTraceResponse
from app.infrastructure.database import get_db_session
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyOrchestrationTraceRepository,
    SQLAlchemyUserRepository,
)

router = APIRouter()


def get_ai_service_client() -> AIServiceClient:
    return AIServiceClient(settings)


@router.post(
    "/coach",
    response_model=CoachResponse,
)
async def coach(
    request: CoachRequest,
    ai_service: Annotated[AIServiceClient, Depends(get_ai_service_client)],
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> CoachResponse:
    enforce_user_access(principal, session, request.user_id)
    user_repository = SQLAlchemyUserRepository(session)
    persisted_snapshot = user_repository.get_financial_snapshot(request.user_id)
    if persisted_snapshot is not None:
        request = request.model_copy(update={"snapshot": persisted_snapshot})
    try:
        response = await ai_service.coach(request)
    except AIServiceUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The coaching service is temporarily unavailable.",
        ) from error
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
    session.commit()
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
