from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.api.financial_schemas import (
    BudgetCategoryResponse,
    BudgetResponse,
    BudgetUpsert,
    DashboardResponse,
    GoalCreate,
    GoalProgressResponse,
    GoalResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileSummary,
    ProfileUpsert,
    SnapshotResponse,
    TransactionCreate,
    TransactionResponse,
)
from app.core.security import require_api_key
from app.domain.schemas import MoneyAmount
from app.infrastructure.database import get_db_session
from app.infrastructure.models import (
    FinancialGoalRecord,
    FinancialProfileRecord,
    MonthlyBudgetRecord,
    TransactionRecord,
)
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyGoalRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyUserRepository,
)

router = APIRouter(dependencies=[Depends(require_api_key)])
UserId = Annotated[str, Path(min_length=1, max_length=128)]


def _validate_period_start(period_start: date) -> None:
    if period_start.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_start must be the first day of a month",
        )


def _profile_response(record: FinancialProfileRecord) -> ProfileResponse:
    income = (
        MoneyAmount(currency=record.currency, amount=float(record.monthly_income))
        if record.monthly_income is not None
        else None
    )
    return ProfileResponse(
        user_id=record.user_id,
        monthly_income=income,
        risk_tolerance=record.risk_tolerance,
        preferences=record.preferences,
    )


def _profile_summary(record: FinancialProfileRecord) -> ProfileSummary:
    display_name = record.preferences.get("display_name")
    if not isinstance(display_name, str) or not display_name.strip():
        display_name = record.user_id
    income = (
        MoneyAmount(currency=record.currency, amount=float(record.monthly_income))
        if record.monthly_income is not None
        else None
    )
    return ProfileSummary(
        user_id=record.user_id,
        display_name=display_name.strip(),
        monthly_income=income,
        risk_tolerance=record.risk_tolerance,
    )


def _transaction_response(record: TransactionRecord) -> TransactionResponse:
    return TransactionResponse(
        id=record.id,
        description=record.description,
        category=record.category,
        amount=MoneyAmount(currency=record.currency, amount=float(record.amount)),
        occurred_on=record.occurred_on,
        recurring=record.recurring,
    )


def _goal_response(record: FinancialGoalRecord) -> GoalResponse:
    return GoalResponse(
        id=record.id,
        name=record.name,
        target_amount=MoneyAmount(currency=record.currency, amount=float(record.target_amount)),
        current_amount=MoneyAmount(currency=record.currency, amount=float(record.current_amount)),
        target_months=record.target_months,
    )


def _budget_response(
    record: MonthlyBudgetRecord, spending: dict[str, float]
) -> BudgetResponse:
    categories = [
        BudgetCategoryResponse(
            category=item.category,
            limit_amount=float(item.limit_amount),
            spent_amount=spending.get(item.category, 0.0),
            remaining_amount=float(item.limit_amount) - spending.get(item.category, 0.0),
        )
        for item in sorted(record.categories, key=lambda category: category.category)
    ]
    total_limit = sum(item.limit_amount for item in categories)
    total_spent = sum(spending.values())
    return BudgetResponse(
        period_start=record.period_start,
        currency=record.currency,
        total_limit=total_limit,
        total_spent=total_spent,
        total_remaining=total_limit - total_spent,
        categories=categories,
    )


@router.get("/profiles", response_model=list[ProfileSummary])
def list_profiles(
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ProfileSummary]:
    records = SQLAlchemyUserRepository(session).list_profiles()
    return [_profile_summary(record) for record in records]


@router.post(
    "/profiles",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_profile(
    profile: ProfileCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> ProfileResponse:
    repository = SQLAlchemyUserRepository(session)
    if repository.get_profile(profile.user_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile already exists",
        )
    record = repository.upsert_profile(
        profile.user_id,
        ProfileUpsert(**profile.model_dump(exclude={"user_id"})),
    )
    session.commit()
    return _profile_response(record)


@router.get("/users/{user_id}/profile", response_model=ProfileResponse)
def get_profile(user_id: UserId, session: Annotated[Session, Depends(get_db_session)]) -> ProfileResponse:
    record = SQLAlchemyUserRepository(session).get_profile(user_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return _profile_response(record)


@router.put("/users/{user_id}/profile", response_model=ProfileResponse)
def put_profile(
    user_id: UserId,
    profile: ProfileUpsert,
    session: Annotated[Session, Depends(get_db_session)],
) -> ProfileResponse:
    record = SQLAlchemyUserRepository(session).upsert_profile(user_id, profile)
    session.commit()
    return _profile_response(record)


@router.get("/users/{user_id}/transactions", response_model=list[TransactionResponse])
def list_transactions(
    user_id: UserId,
    session: Annotated[Session, Depends(get_db_session)],
    period_start: Annotated[date | None, Query()] = None,
) -> list[TransactionResponse]:
    if period_start is not None:
        _validate_period_start(period_start)
    records = SQLAlchemyTransactionRepository(session).list_records(
        user_id, period_start=period_start
    )
    return [_transaction_response(record) for record in records]


@router.post(
    "/users/{user_id}/transactions",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    user_id: UserId,
    transaction: TransactionCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> TransactionResponse:
    record = SQLAlchemyTransactionRepository(session).create(user_id, transaction)
    session.commit()
    return _transaction_response(record)


@router.put(
    "/users/{user_id}/transactions/{transaction_id}", response_model=TransactionResponse
)
def update_transaction(
    user_id: UserId,
    transaction_id: UUID,
    transaction: TransactionCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> TransactionResponse:
    record = SQLAlchemyTransactionRepository(session).update(
        user_id, transaction_id, transaction
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    session.commit()
    return _transaction_response(record)


@router.delete("/users/{user_id}/transactions/{transaction_id}", status_code=204)
def delete_transaction(
    user_id: UserId,
    transaction_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    if not SQLAlchemyTransactionRepository(session).delete(user_id, transaction_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{user_id}/goals", response_model=list[GoalResponse])
def list_goals(
    user_id: UserId, session: Annotated[Session, Depends(get_db_session)]
) -> list[GoalResponse]:
    records = SQLAlchemyGoalRepository(session).list_records(user_id)
    return [_goal_response(record) for record in records]


@router.post(
    "/users/{user_id}/goals",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_goal(
    user_id: UserId,
    goal: GoalCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> GoalResponse:
    try:
        record = SQLAlchemyGoalRepository(session).create(user_id, goal)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    session.commit()
    return _goal_response(record)


@router.put("/users/{user_id}/goals/{goal_id}", response_model=GoalResponse)
def update_goal(
    user_id: UserId,
    goal_id: UUID,
    goal: GoalCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> GoalResponse:
    try:
        record = SQLAlchemyGoalRepository(session).update(user_id, goal_id, goal)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    session.commit()
    return _goal_response(record)


@router.delete("/users/{user_id}/goals/{goal_id}", status_code=204)
def delete_goal(
    user_id: UserId,
    goal_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    if not SQLAlchemyGoalRepository(session).delete(user_id, goal_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{user_id}/snapshot", response_model=SnapshotResponse)
def get_snapshot(
    user_id: UserId, session: Annotated[Session, Depends(get_db_session)]
) -> SnapshotResponse:
    snapshot = SQLAlchemyUserRepository(session).get_financial_snapshot(user_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return SnapshotResponse(user_id=user_id, **snapshot.model_dump())


@router.get("/users/{user_id}/budget", response_model=BudgetResponse)
def get_budget(
    user_id: UserId,
    period_start: Annotated[date, Query()],
    session: Annotated[Session, Depends(get_db_session)],
) -> BudgetResponse:
    _validate_period_start(period_start)
    repository = SQLAlchemyBudgetRepository(session)
    record = repository.get(user_id, period_start)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return _budget_response(record, repository.spending_by_category(user_id, period_start))


@router.put("/users/{user_id}/budget", response_model=BudgetResponse)
def put_budget(
    user_id: UserId,
    budget: BudgetUpsert,
    session: Annotated[Session, Depends(get_db_session)],
) -> BudgetResponse:
    repository = SQLAlchemyBudgetRepository(session)
    record = repository.upsert(user_id, budget)
    session.commit()
    return _budget_response(
        record, repository.spending_by_category(user_id, budget.period_start)
    )


@router.get("/users/{user_id}/dashboard", response_model=DashboardResponse)
def get_dashboard(
    user_id: UserId,
    period_start: Annotated[date, Query()],
    session: Annotated[Session, Depends(get_db_session)],
) -> DashboardResponse:
    _validate_period_start(period_start)
    user_repository = SQLAlchemyUserRepository(session)
    if not user_repository.exists(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    profile = user_repository.get_profile(user_id)
    budget_repository = SQLAlchemyBudgetRepository(session)
    spending = budget_repository.spending_by_category(user_id, period_start)
    total_spent = sum(spending.values())
    monthly_income = float(profile.monthly_income) if profile and profile.monthly_income else 0.0
    currency = profile.currency if profile else "SGD"
    budget_record = budget_repository.get(user_id, period_start)
    goals = [
        GoalProgressResponse(
            id=goal.id,
            name=goal.name,
            current_amount=float(goal.current_amount),
            target_amount=float(goal.target_amount),
            progress_percent=(
                min(float(goal.current_amount) / float(goal.target_amount) * 100, 100.0)
                if goal.target_amount
                else 100.0
            ),
            monthly_required=max(
                (float(goal.target_amount) - float(goal.current_amount)) / goal.target_months,
                0.0,
            ),
        )
        for goal in SQLAlchemyGoalRepository(session).list_records(user_id)
    ]
    available_balance = monthly_income - total_spent
    savings_rate = available_balance / monthly_income * 100 if monthly_income else 0.0
    return DashboardResponse(
        period_start=period_start,
        currency=currency,
        monthly_income=monthly_income,
        total_spent=total_spent,
        available_balance=available_balance,
        savings_rate_percent=savings_rate,
        budget=(
            _budget_response(budget_record, spending) if budget_record is not None else None
        ),
        category_spending=spending,
        goals=goals,
        transaction_count=budget_repository.transaction_count(user_id, period_start),
    )
