from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.api.financial_schemas import (
    AgentExplanationResponse,
    BudgetCategoryResponse,
    BudgetResponse,
    BudgetUpsert,
    ChatExplanationResponse,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionSummary,
    ChatSessionUpdate,
    DashboardResponse,
    DataConsentResponse,
    DataConsentUpdate,
    DataLifecycleResponse,
    DemographicResponse,
    DemographicUpsert,
    FairnessConsentResponse,
    FairnessConsentUpdate,
    FairnessProfileResponse,
    GoalCreate,
    GoalProgressResponse,
    GoalResponse,
    # GoalUpdate,
    ProfileCreate,
    ProfileResponse,
    ProfileSummary,
    ProfileUpsert,
    SnapshotResponse,
    TransactionCreate,
    TransactionResponse,
    UserDataDeletionReceipt,
    UserDataDeletionRequest,
    UserDataExportResponse,
)
from app.core.config import settings
from app.core.data_lifecycle import (
    DATA_EXPORT_SCHEMA_VERSION,
    DATA_LIFECYCLE_POLICY,
    DATA_LIFECYCLE_POLICY_VERSION,
    DURABLE_MEMORY_CONSENT_VERSION,
    DURABLE_MEMORY_PURPOSE,
)
from app.core.security import (
    AuthenticatedPrincipal,
    automation_user_id_allowed,
    automation_user_id_reserved,
    enforce_automation_user_scope,
    require_owned_path_user,
    require_principal,
)
from app.core.telemetry import log_event, trace_method
from app.domain.schemas import MoneyAmount
from app.infrastructure.database import get_db_session
from app.infrastructure.models import (
    ChatMessageRecord,
    ChatSessionRecord,
    FinancialGoalRecord,
    FinancialProfileRecord,
    MonthlyBudgetRecord,
    ProfileConsentRecord,
    ProfileDemographicRecord,
    TransactionRecord,
    UserRecord,
)
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyChatRepository,
    SQLAlchemyConsentRepository,
    SQLAlchemyFairnessProfileRepository,
    SQLAlchemyGoalRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyUserRepository,
)
from app.services.budget_alert import evaluate_budget_alert
from app.services.budget_capture import BudgetDraft
from app.services.budget_constraints import (
    AllocationPolicy,
    AlternativesRequest,
    build_alternatives,
    save_policy,
)
from app.services.budget_continuity import BatchConfirmation, review_due
from app.services.budget_history import AdaptiveRequest, adaptive_review, history
from app.services.budget_income import IncomeScenarios, compare_income
from app.services.budget_reconciliation import save_settings
from app.services.budget_review import build_budget_review
from app.services.budget_scenarios import apply_saved_constraints, compare_draft
from app.services.budget_workspace import WorkspaceChange, confirm_change, context, preview_change
from app.services.cashflow import CashflowSettings, occurs, project_cashflow
from app.services.financial_workspace import lock_workspace, read_section, write_section
from app.services.spending_analyzer import _generate_insights, analyze_spending_patterns

router = APIRouter(dependencies=[Depends(require_owned_path_user)])
UserId = Annotated[str, Path(min_length=1, max_length=128)]


def _validate_period_start(period_start: date) -> None:
    log_event("VV entering ", "app.api.financial", "_validate_period_start")
    if period_start.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_start must be the first day of a month",
        )


def _profile_response(record: FinancialProfileRecord) -> ProfileResponse:
    log_event("VV entering ", "app.api.financial", "_profile_response")
    income = (
        MoneyAmount(currency=record.currency, amount=float(record.monthly_income))
        if record.monthly_income is not None
        else None
    )
    return ProfileResponse(
        user_id=record.user_id,
        monthly_income=income,
        risk_tolerance=record.risk_tolerance,
        employment_status=record.employment_status,
        occupation_category=record.occupation_category,
        income_frequency=record.income_frequency,
        income_stability=record.income_stability,
        household_size=record.household_size,
        dependants=record.dependants,
        housing_status=record.housing_status,
        financial_literacy=record.financial_literacy,
        preferred_language=record.preferred_language,
        accessibility_preferences=record.accessibility_preferences,
        preferences=record.preferences,
    )


def _profile_summary(record: FinancialProfileRecord) -> ProfileSummary:
    log_event("VV entering ", "app.api.financial", "_profile_summary")
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
    log_event("VV entering ", "app.api.financial", "_transaction_response")
    return TransactionResponse(
        id=record.id,
        description=record.description,
        category=record.category,
        amount=MoneyAmount(currency=record.currency, amount=float(record.amount)),
        occurred_on=record.occurred_on,
        recurring=record.recurring,
        recurrence=record.recurrence,
        obligation_id=record.obligation_id,
        transaction_type=record.transaction_type,
    )


def _goal_response(record: FinancialGoalRecord) -> GoalResponse:
    log_event("VV entering ", "app.api.financial", "_goal_response")
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
    log_event("VV entering ", "app.api.financial", "_budget_response")
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
        planning=record.planning,
    )


@trace_method
def _message_explanation(message: ChatMessageRecord) -> ChatExplanationResponse | None:
    log_event("VV entering ", "app.api.financial", "_message_explanation")
    trace = message.orchestration_trace
    if trace is None:
        return None
    return ChatExplanationResponse(
        trace_id=trace.trace_id,
        response_language=trace.audit.get("response_language", "English"),
        selected_agents=trace.selected_agents,
        routing_rationale=trace.audit.get("routing_rationale", []),
        agent_results=[
            AgentExplanationResponse(
                agent=item["agent"],
                rationale=item.get("rationale", []),
                confidence=item.get("confidence", 0.0),
                blocked=item.get("blocked", False),
            )
            for item in trace.agent_results
        ],
        blocked=trace.blocked,
        prompt_set_version=trace.prompt_set_version,
    )


@trace_method
def _chat_session_response(
    record: ChatSessionRecord, *, include_messages: bool
) -> ChatSessionSummary | ChatSessionResponse:
    log_event("VV entering ", "app.api.financial", "_chat_session_response")
    values = {
        "id": record.id,
        "user_id": record.user_id,
        "title": record.title,
        "message_count": len(record.messages),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
    if not include_messages:
        return ChatSessionSummary(**values)
    return ChatSessionResponse(
        **values,
        messages=[
            ChatMessageResponse(
                id=message.id,
                role=message.role,
                content=message.content,
                sources=message.sources,
                explanation=_message_explanation(message),
                created_at=message.created_at,
            )
            for message in record.messages
        ],
    )


@router.get("/profiles", response_model=list[ProfileSummary])
def list_profiles(
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> list[ProfileSummary]:
    log_event("VV entering ", "app.api.financial", "list_profiles")
    repository = SQLAlchemyUserRepository(session)
    if principal.is_automation:
        records = repository.list_profiles()
        records = [
            record for record in records if automation_user_id_allowed(record.user_id)
        ]
    else:
        records = repository.list_profiles_for_owner(
            principal.issuer or "",
            principal.subject or "",
        )
    return [_profile_summary(record) for record in records]


@router.post(
    "/profiles",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_profile(
    profile: ProfileCreate,
    session: Annotated[Session, Depends(get_db_session)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
) -> ProfileResponse:
    log_event("VV entering ", "app.api.financial", "create_profile")
    repository = SQLAlchemyUserRepository(session)
    enforce_automation_user_scope(principal, profile.user_id)
    if not principal.is_automation and automation_user_id_reserved(profile.user_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Profile ID is reserved",
        )
    owner = (
        (None, None)
        if principal.is_automation
        else (principal.issuer, principal.subject)
    )
    try:
        record = repository.create_profile(
            profile.user_id,
            ProfileUpsert(**profile.model_dump(exclude={"user_id"})),
            owner_issuer=owner[0],
            owner_subject=owner[1],
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile already exists",
        ) from None
    session.commit()
    return _profile_response(record)


@router.get("/users/{user_id}/profile", response_model=ProfileResponse)
def get_profile(user_id: UserId, session: Annotated[Session, Depends(get_db_session)]) -> ProfileResponse:
    log_event("VV entering ", "app.api.financial", "get_profile")
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
    log_event("VV entering ", "app.api.financial", "put_profile")
    record = SQLAlchemyUserRepository(session).upsert_profile(user_id, profile)
    session.commit()
    return _profile_response(record)


@router.delete("/users/{user_id}/profile", status_code=204)
def delete_profile(
    user_id: UserId,
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    log_event("VV entering ", "app.api.financial", "delete_profile")
    if not SQLAlchemyUserRepository(session).delete_profile(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/users/{user_id}/chat-sessions",
    response_model=list[ChatSessionSummary],
)
@trace_method
def list_chat_sessions(
    user_id: UserId,
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ChatSessionSummary]:
    log_event("VV entering ", "app.api.financial", "list_chat_sessions")
    records = SQLAlchemyChatRepository(session).list_for_user(user_id)
    return [
        _chat_session_response(record, include_messages=False) for record in records
    ]


@router.post(
    "/users/{user_id}/chat-sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
@trace_method
def create_chat_session(
    user_id: UserId,
    chat: ChatSessionCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> ChatSessionResponse:
    log_event("VV entering ", "app.api.financial", "create_chat_session")
    user_repository = SQLAlchemyUserRepository(session)
    if not user_repository.exists(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    repository = SQLAlchemyChatRepository(session)
    if repository.id_exists(chat.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation already exists",
        )
    record = repository.create(user_id, chat.id, chat.title)
    session.commit()
    return _chat_session_response(record, include_messages=True)


@router.get(
    "/users/{user_id}/chat-sessions/{chat_session_id}",
    response_model=ChatSessionResponse,
)
@trace_method
def get_chat_session(
    user_id: UserId,
    chat_session_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> ChatSessionResponse:
    log_event("VV entering ", "app.api.financial", "get_chat_session")
    record = SQLAlchemyChatRepository(session).get(user_id, chat_session_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return _chat_session_response(record, include_messages=True)


@router.patch(
    "/users/{user_id}/chat-sessions/{chat_session_id}",
    response_model=ChatSessionResponse,
)
def update_chat_session(
    user_id: UserId,
    chat_session_id: str,
    update: ChatSessionUpdate,
    session: Annotated[Session, Depends(get_db_session)],
) -> ChatSessionResponse:
    log_event("VV entering ", "app.api.financial", "update_chat_session")
    record = SQLAlchemyChatRepository(session).rename(
        user_id, chat_session_id, update.title
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    session.commit()
    return _chat_session_response(record, include_messages=True)


@router.delete(
    "/users/{user_id}/chat-sessions/{chat_session_id}", status_code=204
)
def delete_chat_session(
    user_id: UserId,
    chat_session_id: str,
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    log_event("VV entering ", "app.api.financial", "delete_chat_session")
    if not SQLAlchemyChatRepository(session).delete(user_id, chat_session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _fairness_consent_response(
    record: ProfileConsentRecord | None,
) -> FairnessConsentResponse:
    log_event("VV entering ", "app.api.financial", "_fairness_consent_response")
    if record is None:
        return FairnessConsentResponse(
            purpose="fairness_evaluation",
            consent_version="1.0",
            granted=False,
            granted_at=None,
            withdrawn_at=None,
        )
    return FairnessConsentResponse(
        purpose=record.purpose,
        consent_version=record.consent_version,
        granted=record.granted,
        granted_at=record.granted_at,
        withdrawn_at=record.withdrawn_at,
    )


def _durable_memory_consent_response(
    record: ProfileConsentRecord | None,
) -> DataConsentResponse:
    log_event("VV entering ", "app.api.financial", "_durable_memory_consent_response")
    policy_feature_enabled = bool(
        DATA_LIFECYCLE_POLICY["consent"][DURABLE_MEMORY_PURPOSE]["feature_enabled"]
    )
    values = {
        "purpose": DURABLE_MEMORY_PURPOSE,
        "consent_version": DURABLE_MEMORY_CONSENT_VERSION,
        "granted": False,
        "granted_at": None,
        "withdrawn_at": None,
    }
    if record is not None:
        values.update(
            {
                "purpose": record.purpose,
                "consent_version": record.consent_version,
                "granted": record.granted,
                "granted_at": record.granted_at,
                "withdrawn_at": record.withdrawn_at,
            }
        )
    return DataConsentResponse(
        **values,
        feature_enabled=(
            settings.durable_agent_memory_enabled and policy_feature_enabled
        ),
    )


def _data_lifecycle_response(
    consent: ProfileConsentRecord | None,
) -> DataLifecycleResponse:
    log_event("VV entering ", "app.api.financial", "_data_lifecycle_response")
    return DataLifecycleResponse(
        policy_version=DATA_LIFECYCLE_POLICY_VERSION,
        effective_on=date.fromisoformat(DATA_LIFECYCLE_POLICY["effective_on"]),
        export_schema_version=DATA_EXPORT_SCHEMA_VERSION,
        retention=_effective_retention(),
        durable_memory=_durable_memory_consent_response(consent),
    )


def _effective_retention() -> dict[str, int | str]:
    log_event("VV entering ", "app.api.financial", "_effective_retention")
    return {
        "authenticated_financial_workspace": "until_owner_deletion",
        "orchestration_traces_days": settings.trace_retention_days,
        "chat_history_days": settings.chat_retention_days,
        "synthetic_automation_users_days": settings.synthetic_user_retention_days,
    }


@router.get(
    "/users/{user_id}/data-lifecycle",
    response_model=DataLifecycleResponse,
)
def get_data_lifecycle(
    user_id: UserId,
    session: Annotated[Session, Depends(get_db_session)],
) -> DataLifecycleResponse:
    log_event("VV entering ", "app.api.financial", "get_data_lifecycle")
    if not SQLAlchemyUserRepository(session).exists(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    consent = SQLAlchemyConsentRepository(session).get(
        user_id, DURABLE_MEMORY_PURPOSE
    )
    return _data_lifecycle_response(consent)


@router.put(
    "/users/{user_id}/memory-consent",
    response_model=DataConsentResponse,
)
def put_memory_consent(
    user_id: UserId,
    update: DataConsentUpdate,
    session: Annotated[Session, Depends(get_db_session)],
) -> DataConsentResponse:
    log_event("VV entering ", "app.api.financial", "put_memory_consent")
    if not SQLAlchemyUserRepository(session).exists(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    record = SQLAlchemyConsentRepository(session).set_durable_memory_consent(
        user_id, update.granted
    )
    session.commit()
    return _durable_memory_consent_response(record)


@router.get(
    "/users/{user_id}/data-export",
    response_model=UserDataExportResponse,
)
def export_user_data(
    user_id: UserId,
    session: Annotated[Session, Depends(get_db_session)],
) -> UserDataExportResponse:
    log_event("VV entering ", "app.api.financial", "export_user_data")
    repository = SQLAlchemyUserRepository(session)
    data = repository.export_user_data(user_id)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user = session.get(UserRecord, user_id)
    return UserDataExportResponse(
        schema_version=DATA_EXPORT_SCHEMA_VERSION,
        policy_version=DATA_LIFECYCLE_POLICY_VERSION,
        exported_at=datetime.now(UTC),
        user_id=user_id,
        ownership={"authenticated_owner_bound": bool(user and user.owner_issuer)},
        retention=_effective_retention(),
        data=data,
    )


@router.delete(
    "/users/{user_id}/data",
    response_model=UserDataDeletionReceipt,
)
def delete_user_data(
    user_id: UserId,
    request: UserDataDeletionRequest,
    session: Annotated[Session, Depends(get_db_session)],
) -> UserDataDeletionReceipt:
    log_event("VV entering ", "app.api.financial", "delete_user_data")
    if request.confirm_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="confirm_user_id must match the user being deleted",
        )
    if request.policy_version != DATA_LIFECYCLE_POLICY_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Data lifecycle policy version has changed; review it before deleting",
        )
    deleted_counts = SQLAlchemyUserRepository(session).delete_user_data(user_id)
    if deleted_counts is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    receipt = UserDataDeletionReceipt(
        request_id=uuid4(),
        policy_version=DATA_LIFECYCLE_POLICY_VERSION,
        completed_at=datetime.now(UTC),
        deleted_counts=deleted_counts,
    )
    session.commit()
    return receipt


def _demographic_response(record: ProfileDemographicRecord) -> DemographicResponse:
    log_event("VV entering ", "app.api.financial", "_demographic_response")
    return DemographicResponse(
        user_id=record.user_id,
        age_band=record.age_band,
        gender_identity=record.gender_identity,
        race_ethnicity=record.race_ethnicity,
        nationality_residency=record.nationality_residency,
        disability_status=record.disability_status,
        marital_status=record.marital_status,
        residential_region=record.residential_region,
    )


@router.get(
    "/users/{user_id}/fairness-profile",
    response_model=FairnessProfileResponse,
)
def get_fairness_profile(
    user_id: UserId,
    session: Annotated[Session, Depends(get_db_session)],
) -> FairnessProfileResponse:
    log_event("VV entering ", "app.api.financial", "get_fairness_profile")
    if not SQLAlchemyUserRepository(session).exists(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    repository = SQLAlchemyFairnessProfileRepository(session)
    demographics = repository.get_demographics(user_id)
    return FairnessProfileResponse(
        consent=_fairness_consent_response(repository.get_consent(user_id)),
        demographics=(
            _demographic_response(demographics) if demographics is not None else None
        ),
    )


@router.put(
    "/users/{user_id}/fairness-consent",
    response_model=FairnessConsentResponse,
)
def put_fairness_consent(
    user_id: UserId,
    update: FairnessConsentUpdate,
    session: Annotated[Session, Depends(get_db_session)],
) -> FairnessConsentResponse:
    log_event("VV entering ", "app.api.financial", "put_fairness_consent")
    if not SQLAlchemyUserRepository(session).exists(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    record = SQLAlchemyFairnessProfileRepository(session).set_consent(
        user_id, update.granted
    )
    session.commit()
    return _fairness_consent_response(record)


@router.put(
    "/users/{user_id}/demographics",
    response_model=DemographicResponse,
)
def put_demographics(
    user_id: UserId,
    demographics: DemographicUpsert,
    session: Annotated[Session, Depends(get_db_session)],
) -> DemographicResponse:
    log_event("VV entering ", "app.api.financial", "put_demographics")
    try:
        record = SQLAlchemyFairnessProfileRepository(session).upsert_demographics(
            user_id, demographics
        )
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    session.commit()
    return _demographic_response(record)


@router.get("/users/{user_id}/transactions", response_model=list[TransactionResponse])
def list_transactions(
    user_id: UserId,
    session: Annotated[Session, Depends(get_db_session)],
    period_start: Annotated[date | None, Query()] = None,
) -> list[TransactionResponse]:
    log_event("VV entering ", "app.api.financial", "list_transactions")
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
    log_event("VV entering ", "app.api.financial", "create_transaction")
    try:
        record = SQLAlchemyTransactionRepository(session).create(user_id, transaction)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    log_event(
        "transaction.added",
        source="api",
        category=transaction.category,
    )
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
    log_event("VV entering ", "app.api.financial", "update_transaction")
    try:
        record = SQLAlchemyTransactionRepository(session).update(
            user_id, transaction_id, transaction
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
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
    log_event("VV entering ", "app.api.financial", "delete_transaction")
    try:
        deleted = SQLAlchemyTransactionRepository(session).delete(user_id, transaction_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{user_id}/goals", response_model=list[GoalResponse])
def list_goals(
    user_id: UserId, session: Annotated[Session, Depends(get_db_session)]
) -> list[GoalResponse]:
    log_event("VV entering ", "app.api.financial", "list_goals")
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
    log_event("VV entering ", "app.api.financial", "create_goal")
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
    log_event("VV entering ", "app.api.financial", "update_goal")
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
    log_event("VV entering ", "app.api.financial", "delete_goal")
    if not SQLAlchemyGoalRepository(session).delete(user_id, goal_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/users/{user_id}/snapshot", response_model=SnapshotResponse)
def get_snapshot(
    user_id: UserId, session: Annotated[Session, Depends(get_db_session)]
) -> SnapshotResponse:
    log_event("VV entering ", "app.api.financial", "get_snapshot")
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
    log_event("VV entering ", "app.api.financial", "get_budget")
    _validate_period_start(period_start)
    repository = SQLAlchemyBudgetRepository(session)
    record = repository.get(user_id, period_start)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return _budget_response(record, repository.spending_by_category(user_id, period_start, currency=record.currency))


@router.get("/users/{user_id}/budget/review")
def review_budget(user_id: UserId, period_start: Annotated[date, Query()],
                  session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "review_budget")
    _validate_period_start(period_start)
    return build_budget_review(session, user_id, period_start)


@router.get("/users/{user_id}/budgets")
def list_budgets(user_id: UserId, session: Annotated[Session, Depends(get_db_session)],
                 start: date | None = None, end: date | None = None):
    log_event("VV entering ", "app.api.financial", "list_budgets")
    from coach_math.budget_scope import BudgetScope

    from app.services.budget_records import build_record_change
    try:
        scope = BudgetScope(kind="range", start=start, end=end) if start or end else BudgetScope(kind="all")
        _, result = build_record_change(session, user_id, {"action": "read", "scope": scope.model_dump(mode="json")})
        return result
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/users/{user_id}/budget/compare")
def compare_budget(user_id: UserId, draft: BudgetDraft, session: Annotated[Session, Depends(get_db_session)]):
    # The caller supplies an exploratory plan. Ownership is checked by the router;
    # no saved budget, profile or conversation state is written here.
    log_event("VV entering ", "app.api.financial", "compare_budget")
    return apply_saved_constraints(session, user_id, compare_draft(draft))


@router.put("/users/{user_id}/budget", response_model=BudgetResponse)
def put_budget(
    user_id: UserId,
    budget: BudgetUpsert,
    session: Annotated[Session, Depends(get_db_session)],
) -> BudgetResponse:
    log_event("VV entering ", "app.api.financial", "put_budget")
    repository = SQLAlchemyBudgetRepository(session)
    if budget.review_evidence and build_budget_review(session, user_id, budget.period_start)["evidence_fingerprint"] != budget.review_evidence:
        raise HTTPException(status_code=409, detail="Budget or spending records changed. Refresh the review before saving its adjustment.")
    try:
        record = repository.upsert(user_id, budget)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _budget_response(
        record, repository.spending_by_category(user_id, budget.period_start, currency=record.currency)
    )


@router.get("/users/{user_id}/dashboard", response_model=DashboardResponse)
def get_dashboard(
    user_id: UserId,
    period_start: Annotated[date, Query()],
    session: Annotated[Session, Depends(get_db_session)],
) -> DashboardResponse:
    log_event("VV entering ", "app.api.financial", "get_dashboard")
    _validate_period_start(period_start)
    user_repository = SQLAlchemyUserRepository(session)
    if not user_repository.exists(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    profile = user_repository.get_profile(user_id)
    budget_repository = SQLAlchemyBudgetRepository(session)
    spending = budget_repository.spending_by_category(user_id, period_start, currency="SGD")
    total_spent = sum(spending.values())
    monthly_income = float(profile.monthly_income) if profile and profile.currency == "SGD" and profile.monthly_income else 0.0
    currency = "SGD"
    budget_record = budget_repository.get(user_id, period_start)
    if budget_record and budget_record.currency != currency:
        budget_record = None
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
        if goal.currency == currency
    ]
    available_balance = monthly_income - total_spent
    savings_rate = available_balance / monthly_income * 100 if monthly_income else 0.0
    
    # NEW: Generate spending insights from 6 months of transaction history
    spending_insights = []
    spending_data_quality = "insufficient"
    spending_months_analyzed = 0
    
    try:
        # Fetch 6 months of transactions
        six_months_ago = period_start
        for _ in range(6):
            six_months_ago = (six_months_ago - timedelta(days=1)).replace(day=1)
        from app.infrastructure.repositories import next_month
        historical_transactions = budget_repository.get_transactions_in_range(
            user_id, six_months_ago, next_month(period_start) - timedelta(days=1), currency=currency
        )
        
        if len(historical_transactions) >= 10:
            # Convert to analyzer format
            txn_list = [
                {
                    "category": txn.category,
                    "amount": {"currency": "SGD", "amount": float(txn.amount)},
                    "occurred_on": txn.occurred_on.isoformat(),
                }
                for txn in historical_transactions
            ]
            
            # Run analysis
            analysis_result = analyze_spending_patterns(txn_list, period_start)
            
            # Generate insights
            spending_insights = _generate_insights(analysis_result, period_start)
            spending_data_quality = analysis_result["data_quality"]
            spending_months_analyzed = analysis_result["months_analyzed"]
    except (KeyError, TypeError, ValueError) as insight_error:
        # Gracefully degrade - insights are optional
        log_event("dashboard.spending_insights_failed", error=str(insight_error))
    
    from app.services.budget_timing import saved_timing
    return DashboardResponse(
        budget_timing=saved_timing(session, user_id, period_start),
        review_reminder=review_due(session, user_id),
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
        transaction_count=budget_repository.transaction_count(user_id, period_start, currency=currency),
        spending_insights=spending_insights,
        spending_data_quality=spending_data_quality,
        spending_months_analyzed=spending_months_analyzed,
        budget_alert=evaluate_budget_alert(
            monthly_income,
            (
                [(item.category, float(item.limit_amount)) for item in budget_record.categories]
                if budget_record is not None
                else []
            ),
            spending,
        ),
    )


@router.get("/users/{user_id}/cashflow/settings")
def get_cashflow_settings(user_id: UserId, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "get_cashflow_settings")
    return read_section(session, user_id, "cashflow")


@router.put("/users/{user_id}/cashflow/settings")
def put_cashflow_settings(user_id: UserId, payload: CashflowSettings, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "put_cashflow_settings")
    try:
        result = save_settings(session, user_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return result


@router.get("/users/{user_id}/cashflow")
def get_cashflow(user_id: UserId, through: date, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "get_cashflow")
    try:
        return project_cashflow(session, user_id, through)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/users/{user_id}/cashflow/settle")
def settle_cashflow_occurrence(user_id: UserId, schedule_id: str, due_on: date, session: Annotated[Session, Depends(get_db_session)], settled: bool = True):
    log_event("VV entering ", "app.api.financial", "settle_cashflow_occurrence")
    lock_workspace(session, user_id)
    raw = read_section(session, user_id, "cashflow")
    if raw is None:
        raise HTTPException(status_code=404, detail="Cash-flow settings not found")
    config = CashflowSettings.model_validate(raw)
    schedule = next((item for item in config.schedules if item.id == schedule_id), None)
    if schedule is None or not occurs(schedule, due_on):
        raise HTTPException(status_code=422, detail="Select a valid schedule occurrence")
    if settled and due_on not in schedule.settled_dates:
        schedule.settled_dates.append(due_on)
    elif not settled:
        schedule.settled_dates = [day for day in schedule.settled_dates if day != due_on]
    config = CashflowSettings.model_validate(config.model_dump())
    try:
        result = save_settings(session, user_id, config)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return result


@router.get("/users/{user_id}/budget/commitments")
def get_commitments(user_id: UserId, period_start: date, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "get_commitments")
    _validate_period_start(period_start)
    return read_section(session, user_id, "constraints:" + period_start.isoformat()) or {}

@router.put("/users/{user_id}/budget/commitments")
def put_commitments(user_id: UserId, policy: AllocationPolicy, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "put_commitments")
    try:
        result = save_policy(session, user_id, policy)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return result

@router.post("/users/{user_id}/budget/alternatives")
def funded_alternatives(user_id: UserId, request: AlternativesRequest, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "funded_alternatives")
    _validate_period_start(request.period_start)
    try:
        return build_alternatives(session, user_id, request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/users/{user_id}/budget/workspace")
def get_planning_workspace(user_id: UserId, session: Annotated[Session, Depends(get_db_session)], search: str = Query(default="", max_length=100), offset: int = Query(default=0, ge=0)):
    log_event("VV entering ", "app.api.financial", "get_planning_workspace")
    return context(session, user_id, search=search, offset=offset)


@router.post("/users/{user_id}/budget/workspace/preview")
def preview_planning_change(user_id: UserId, payload: WorkspaceChange, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "preview_planning_change")
    try:
        preview = preview_change(session, user_id, payload)
        write_section(session, user_id, "pending_workspace", preview)
        session.commit()
        return preview
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/users/{user_id}/budget/workspace/confirm")
def confirm_planning_change(user_id: UserId, payload: BatchConfirmation, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "confirm_planning_change")
    lock_workspace(session, user_id)
    pending = read_section(session, user_id, "pending_workspace")
    if not pending or pending["preview_id"] != payload.preview_id:
        raise HTTPException(status_code=409, detail="Preview not found or already consumed")
    try:
        result = confirm_change(session, user_id, pending)
        write_section(session, user_id, "pending_workspace", None)
        session.commit()
        return {"saved": True, "result": result}
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/users/{user_id}/budget/timing")
def get_budget_timing(user_id: UserId, period_start: date, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "get_budget_timing")
    from app.services.budget_timing import saved_timing
    _validate_period_start(period_start)
    return saved_timing(session, user_id, period_start)


@router.post("/users/{user_id}/budget/income-scenarios")
def income_scenarios(user_id: UserId, payload: IncomeScenarios, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "income_scenarios")
    try:
        return compare_income(session, user_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/users/{user_id}/budget/history")
def budget_history(user_id: UserId, period_start: date, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "budget_history")
    _validate_period_start(period_start)
    return history(session, user_id, period_start)


@router.post("/users/{user_id}/budget/adaptive-review")
def adaptive_budget_review(user_id: UserId, payload: AdaptiveRequest, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "adaptive_budget_review")
    try:
        return adaptive_review(session, user_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/users/{user_id}/cashflow/match-candidates")
def cashflow_match_candidates(user_id: UserId, transaction_id: UUID, session: Annotated[Session, Depends(get_db_session)]):
    log_event("VV entering ", "app.api.financial", "cashflow_match_candidates")
    from app.services.budget_reconciliation import match_candidates
    try:
        return match_candidates(session, user_id, transaction_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
