from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.clients.ai_service import AIServiceClient, AIServiceUnavailableError
from app.core.config import settings
from app.core.security import require_api_key
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.database import get_db_session
from app.infrastructure.repositories import SQLAlchemyUserRepository

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
    persisted_snapshot = SQLAlchemyUserRepository(session).get_financial_snapshot(
        request.user_id
    )
    if persisted_snapshot is not None:
        request = request.model_copy(update={"snapshot": persisted_snapshot})
    try:
        return await ai_service.coach(request)
    except AIServiceUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The coaching service is temporarily unavailable.",
        ) from error
