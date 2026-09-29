from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.core.security import require_owned_path_user
from app.infrastructure.database import get_db_session
from app.services.budget_continuity import (
    BatchConfirmation,
    ContinuityRequest,
    ReviewAcknowledgement,
    ReviewPreferences,
    acknowledge_review,
    confirm_batch,
    preview_batch,
    review_due,
)
from app.services.financial_workspace import read_section, write_section

router = APIRouter(dependencies=[Depends(require_owned_path_user)])
UserId = Annotated[str, Path(min_length=1, max_length=128)]
Database = Annotated[Session, Depends(get_db_session)]


@router.post("/users/{user_id}/budget/continuity/preview")
def preview(user_id: UserId, request: ContinuityRequest, session: Database):
    try:
        result = preview_batch(session, user_id, request)
        session.commit()
        return result
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/users/{user_id}/budget/continuity/confirm")
def confirm(user_id: UserId, request: BatchConfirmation, session: Database):
    try:
        result = confirm_batch(session, user_id, request)
        session.commit()
        return result
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/users/{user_id}/budget/reviews/preferences")
def preferences(user_id: UserId, session: Database):
    return read_section(session, user_id, "review_preferences") or {
        "enabled": False,
        "cadence": "monthly",
        "next_review_on": None,
    }


@router.put("/users/{user_id}/budget/reviews/preferences")
def save_preferences(user_id: UserId, request: ReviewPreferences, session: Database):
    result = write_section(session, user_id, "review_preferences", request.model_dump(mode="json"))
    session.commit()
    return result


@router.get("/users/{user_id}/budget/reviews/due")
def due(user_id: UserId, session: Database):
    return review_due(session, user_id, include_review=True)


@router.post("/users/{user_id}/budget/reviews/acknowledge")
def acknowledge(user_id: UserId, request: ReviewAcknowledgement, session: Database):
    try:
        result = acknowledge_review(session, user_id, request)
        session.commit()
        return result
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
