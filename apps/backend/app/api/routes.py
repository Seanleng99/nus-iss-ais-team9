from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.clients.ai_service import AIServiceClient, AIServiceUnavailableError
from app.core.config import settings
from app.core.security import require_api_key
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.database import get_db_session
from app.infrastructure.repositories import SQLAlchemyChatRepository, SQLAlchemyUserRepository

router = APIRouter()


def get_ai_service_client() -> AIServiceClient:
    return AIServiceClient(settings)


@router.post(
    "/coach",
    response_model=CoachResponse,
    dependencies=[Depends(require_api_key)],
)
async def coach(
    request: CoachRequest,
    ai_service: Annotated[AIServiceClient, Depends(get_ai_service_client)],
    session: Annotated[Session, Depends(get_db_session)],
) -> CoachResponse:
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
    chat_repository.append_message(
        chat_session,
        "assistant",
        response.answer,
        [source.model_dump() for source in response.sources],
    )
    session.commit()
    return response
