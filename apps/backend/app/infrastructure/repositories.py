from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, case, delete, func, or_, select, update
from sqlalchemy.orm import Session, load_only, selectinload

from app.api.financial_schemas import (
    BudgetUpsert,
    DemographicUpsert,
    GoalCreate,
    ProfileUpsert,
    TransactionCreate,
)
from app.core.data_lifecycle import (
    DURABLE_MEMORY_CONSENT_VERSION,
    DURABLE_MEMORY_PURPOSE,
)
from app.core.telemetry import trace_method
from app.domain.schemas import (
    SAFE_REFUSAL_TEMPLATES,
    FinancialGoal,
    MoneyAmount,
    Transaction,
    UserFinancialSnapshot,
    blocked_response_answer,
    sanitize_blocked_agent_results,
    sanitize_blocked_audit,
)
from app.infrastructure.models import (
    BudgetCategoryRecord,
    ChatMessageRecord,
    ChatSessionRecord,
    FinancialGoalRecord,
    FinancialProfileRecord,
    MonthlyBudgetRecord,
    OrchestrationTraceRecord,
    PlanningPreferencesRecord,
    ProfileConsentRecord,
    ProfileDemographicRecord,
    TransactionRecord,
    UserRecord,
)

FAIRNESS_EVALUATION_PURPOSE = "fairness_evaluation"
FAIRNESS_CONSENT_VERSION = "1.0"


@trace_method
def _lock_user_lifecycle(session: Session, user_id: str) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    # Serialize creation and deletion even when the user row does not exist yet.
    # A row lock alone cannot protect that initial-insert boundary.
    session.scalar(
        select(func.pg_advisory_xact_lock(2_254_477, func.hashtext(user_id)))
    )


@trace_method
def _ensure_user(session: Session, user_id: str) -> UserRecord:
    _lock_user_lifecycle(session, user_id)
    user = session.get(UserRecord, user_id)
    if user is None:
        user = UserRecord(id=user_id)
        session.add(user)
        session.flush()
    user.last_activity_at = datetime.now(UTC)
    return user


@trace_method
def _touch_user(session: Session, user_id: str) -> None:
    user = session.get(UserRecord, user_id)
    if user is not None:
        user.last_activity_at = datetime.now(UTC)


def next_month(period_start: date) -> date:
    if period_start.month == 12:
        return date(period_start.year + 1, 1, 1)
    return date(period_start.year, period_start.month + 1, 1)


class SQLAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @trace_method
    def get_profile(self, user_id: str) -> FinancialProfileRecord | None:
        return self.session.get(FinancialProfileRecord, user_id)

    def list_profiles(self) -> list[FinancialProfileRecord]:
        query = select(FinancialProfileRecord).order_by(
            FinancialProfileRecord.updated_at.desc(),
            FinancialProfileRecord.user_id,
        )
        return list(self.session.scalars(query))

    def list_profiles_for_owner(
        self, owner_issuer: str, owner_subject: str
    ) -> list[FinancialProfileRecord]:
        query = (
            select(FinancialProfileRecord)
            .join(UserRecord, UserRecord.id == FinancialProfileRecord.user_id)
            .where(
                UserRecord.owner_issuer == owner_issuer,
                UserRecord.owner_subject == owner_subject,
            )
            .order_by(
                FinancialProfileRecord.updated_at.desc(),
                FinancialProfileRecord.user_id,
            )
        )
        return list(self.session.scalars(query))

    def exists(self, user_id: str) -> bool:
        return self.session.get(UserRecord, user_id) is not None

    def create_profile(
        self,
        user_id: str,
        profile: ProfileUpsert,
        *,
        owner_issuer: str | None = None,
        owner_subject: str | None = None,
    ) -> FinancialProfileRecord:
        _lock_user_lifecycle(self.session, user_id)
        if self.session.get(UserRecord, user_id) is not None:
            raise ValueError("Profile already exists")
        if (owner_issuer is None) != (owner_subject is None):
            raise ValueError("Owner identity must be complete")
        self.session.add(
            UserRecord(
                id=user_id,
                owner_issuer=owner_issuer,
                owner_subject=owner_subject,
            )
        )
        self.session.flush()
        return self.upsert_profile(user_id, profile)

    def upsert_profile(self, user_id: str, profile: ProfileUpsert) -> FinancialProfileRecord:
        _ensure_user(self.session, user_id)
        record = self.get_profile(user_id)
        if record is None:
            record = FinancialProfileRecord(user_id=user_id)
            self.session.add(record)

        income = profile.monthly_income
        record.monthly_income = income.amount if income else None
        record.currency = income.currency if income else "SGD"
        record.risk_tolerance = profile.risk_tolerance
        record.employment_status = profile.employment_status
        record.occupation_category = profile.occupation_category
        record.income_frequency = profile.income_frequency
        record.income_stability = profile.income_stability
        record.household_size = profile.household_size
        record.dependants = profile.dependants
        record.housing_status = profile.housing_status
        record.financial_literacy = profile.financial_literacy
        record.preferred_language = profile.preferred_language
        record.accessibility_preferences = profile.accessibility_preferences
        record.preferences = profile.preferences
        self.session.flush()
        return record

    def delete_profile(self, user_id: str) -> bool:
        _lock_user_lifecycle(self.session, user_id)
        user = self.session.get(UserRecord, user_id)
        if user is None or self.get_profile(user_id) is None:
            return False
        self.session.delete(user)
        self.session.flush()
        return True

    def export_user_data(self, user_id: str) -> dict[str, Any] | None:
        user = self.session.get(UserRecord, user_id)
        if user is None:
            return None
        profile = self.get_profile(user_id)
        demographics = self.session.get(ProfileDemographicRecord, user_id)
        consents = list(
            self.session.scalars(
                select(ProfileConsentRecord)
                .where(ProfileConsentRecord.user_id == user_id)
                .order_by(ProfileConsentRecord.purpose)
            )
        )
        transactions = list(
            self.session.scalars(
                SQLAlchemyTransactionRepository._query(user_id)
            )
        )
        goals = SQLAlchemyGoalRepository(self.session).list_records(user_id)
        budgets = list(
            self.session.scalars(
                select(MonthlyBudgetRecord)
                .options(selectinload(MonthlyBudgetRecord.categories))
                .where(MonthlyBudgetRecord.user_id == user_id)
                .order_by(MonthlyBudgetRecord.period_start)
            )
        )
        chat_sessions = list(
            self.session.scalars(
                select(ChatSessionRecord)
                .options(
                    selectinload(ChatSessionRecord.messages).selectinload(
                        ChatMessageRecord.orchestration_trace
                    )
                )
                .where(ChatSessionRecord.user_id == user_id)
                .order_by(ChatSessionRecord.created_at)
            )
        )
        return {
            "profile": (
                {
                    "monthly_income": (
                        {
                            "currency": profile.currency,
                            "amount": float(profile.monthly_income),
                        }
                        if profile.monthly_income is not None
                        else None
                    ),
                    "risk_tolerance": profile.risk_tolerance,
                    "employment_status": profile.employment_status,
                    "occupation_category": profile.occupation_category,
                    "income_frequency": profile.income_frequency,
                    "income_stability": profile.income_stability,
                    "household_size": profile.household_size,
                    "dependants": profile.dependants,
                    "housing_status": profile.housing_status,
                    "financial_literacy": profile.financial_literacy,
                    "preferred_language": profile.preferred_language,
                    "accessibility_preferences": profile.accessibility_preferences,
                    "preferences": profile.preferences,
                }
                if profile is not None
                else None
            ),
            "demographics": (
                {
                    "age_band": demographics.age_band,
                    "gender_identity": demographics.gender_identity,
                    "race_ethnicity": demographics.race_ethnicity,
                    "nationality_residency": demographics.nationality_residency,
                    "disability_status": demographics.disability_status,
                    "marital_status": demographics.marital_status,
                    "residential_region": demographics.residential_region,
                }
                if demographics is not None
                else None
            ),
            "consents": [
                {
                    "purpose": record.purpose,
                    "consent_version": record.consent_version,
                    "granted": record.granted,
                    "granted_at": (
                        record.granted_at.isoformat() if record.granted_at else None
                    ),
                    "withdrawn_at": (
                        record.withdrawn_at.isoformat() if record.withdrawn_at else None
                    ),
                }
                for record in consents
            ],
            "planning_preferences": (self.session.get(PlanningPreferencesRecord, user_id).data if self.session.get(PlanningPreferencesRecord, user_id) else {}),
            "transactions": [
                {
                    "id": str(record.id),
                    "description": record.description,
                    "category": record.category,
                    "amount": {
                        "currency": record.currency,
                        "amount": float(record.amount),
                    },
                    "occurred_on": record.occurred_on.isoformat(),
                    "recurring": record.recurring,
                    "transaction_type": record.transaction_type,
                }
                for record in transactions
            ],
            "goals": [
                {
                    "id": str(record.id),
                    "name": record.name,
                    "target_amount": {
                        "currency": record.currency,
                        "amount": float(record.target_amount),
                    },
                    "current_amount": {
                        "currency": record.currency,
                        "amount": float(record.current_amount),
                    },
                    "target_months": record.target_months,
                }
                for record in goals
            ],
            "budgets": [
                {
                    "period_start": record.period_start.isoformat(),
                    "currency": record.currency,
                    "planning": record.planning,
                    "categories": [
                        {
                            "category": category.category,
                            "limit_amount": float(category.limit_amount),
                        }
                        for category in sorted(
                            record.categories, key=lambda item: item.category
                        )
                    ],
                }
                for record in budgets
            ],
            "incomplete_orchestration_traces": [
                {
                    "trace_id": trace.trace_id, "session_id": trace.session_id,
                    "status": trace.status, "correlation_id": trace.correlation_id,
                    "error_code": trace.error_code, "audit": trace.audit,
                    "created_at": trace.created_at.isoformat(),
                    "finished_at": trace.finished_at.isoformat() if trace.finished_at else None,
                }
                for chat in chat_sessions for trace in chat.traces
                if trace.assistant_message_id is None
            ],
            "chat_sessions": [
                {
                    "id": record.id,
                    "title": record.title,
                    "created_at": record.created_at.isoformat(),
                    "updated_at": record.updated_at.isoformat(),
                    "messages": [
                        {
                            "id": str(message.id),
                            "role": message.role,
                            "content": (
                                blocked_response_answer(
                                    response_language=message.orchestration_trace.audit.get(
                                        "response_language", "English"
                                    ),
                                    answer=message.content,
                                )
                                if message.role == "assistant"
                                and message.orchestration_trace is not None
                                and message.orchestration_trace.blocked
                                else message.content
                            ),
                            "sources": (
                                []
                                if message.role == "assistant"
                                and message.orchestration_trace is not None
                                and message.orchestration_trace.blocked
                                else message.sources
                            ),
                            "created_at": message.created_at.isoformat(),
                            "orchestration_trace": (
                                {
                                    "trace_id": message.orchestration_trace.trace_id,
                                    "status": message.orchestration_trace.status,
                                    "correlation_id": message.orchestration_trace.correlation_id,
                                    "selected_agents": message.orchestration_trace.selected_agents,
                                    "agent_results": (
                                        sanitize_blocked_agent_results(
                                            message.orchestration_trace.agent_results,
                                            response_language=message.orchestration_trace.audit.get(
                                                "response_language", "English"
                                            ),
                                        )
                                        if message.orchestration_trace.blocked
                                        else message.orchestration_trace.agent_results
                                    ),
                                    "audit": (
                                        sanitize_blocked_audit(
                                            message.orchestration_trace.audit
                                        )
                                        if message.orchestration_trace.blocked
                                        else message.orchestration_trace.audit
                                    ),
                                    "blocked": message.orchestration_trace.blocked,
                                    "model_provider": message.orchestration_trace.model_provider,
                                    "model_id": message.orchestration_trace.model_id,
                                    "prompt_set_version": message.orchestration_trace.prompt_set_version,
                                    "created_at": message.orchestration_trace.created_at.isoformat(),
                                }
                                if message.orchestration_trace is not None
                                else None
                            ),
                        }
                        for message in record.messages
                    ],
                }
                for record in chat_sessions
            ],
        }

    def delete_user_data(self, user_id: str) -> dict[str, int] | None:
        _lock_user_lifecycle(self.session, user_id)
        user = self.session.get(UserRecord, user_id)
        if user is None:
            return None

        def count(model: type[Any]) -> int:
            return int(
                self.session.scalar(
                    select(func.count()).select_from(model).where(model.user_id == user_id)
                )
                or 0
            )

        counts = {
            "profiles": count(FinancialProfileRecord),
            "demographics": count(ProfileDemographicRecord),
            "consents": count(ProfileConsentRecord),
            "transactions": count(TransactionRecord),
            "goals": count(FinancialGoalRecord),
            "budgets": count(MonthlyBudgetRecord),
            "budget_categories": int(
                self.session.scalar(
                    select(func.count())
                    .select_from(BudgetCategoryRecord)
                    .join(MonthlyBudgetRecord)
                    .where(MonthlyBudgetRecord.user_id == user_id)
                )
                or 0
            ),
            "chat_sessions": count(ChatSessionRecord),
            "chat_messages": int(
                self.session.scalar(
                    select(func.count())
                    .select_from(ChatMessageRecord)
                    .join(ChatSessionRecord)
                    .where(ChatSessionRecord.user_id == user_id)
                )
                or 0
            ),
            "orchestration_traces": int(
                self.session.scalar(
                    select(func.count())
                    .select_from(OrchestrationTraceRecord)
                    .join(ChatSessionRecord)
                    .where(ChatSessionRecord.user_id == user_id)
                )
                or 0
            ),
        }
        self.session.delete(user)
        self.session.flush()
        return counts

    def delete_if_empty(self, user_id: str) -> bool:
        _lock_user_lifecycle(self.session, user_id)
        user = self.session.get(UserRecord, user_id)
        if user is None:
            return False
        owned_models = (
            PlanningPreferencesRecord,            FinancialProfileRecord,
            ProfileDemographicRecord,
            ProfileConsentRecord,
            TransactionRecord,
            FinancialGoalRecord,
            MonthlyBudgetRecord,
            ChatSessionRecord,
        )
        if any(
            self.session.scalar(
                select(model.user_id).where(model.user_id == user_id).limit(1)
            )
            is not None
            for model in owned_models
        ):
            return False
        self.session.delete(user)
        self.session.flush()
        return True

    @trace_method
    def get_financial_snapshot(self, user_id: str) -> UserFinancialSnapshot | None:
        if self.session.get(UserRecord, user_id) is None:
            return None

        profile = self.get_profile(user_id)
        transaction_repository = SQLAlchemyTransactionRepository(self.session)
        goal_repository = SQLAlchemyGoalRepository(self.session)
        transactions = transaction_repository.list_for_user(user_id)
        goals = goal_repository.list_for_user(user_id)

        # Chat persistence creates a bare user record. It must not turn an empty
        # database snapshot into an authoritative replacement for caller-supplied
        # financial context on later coaching requests.
        if profile is None and not transactions and not goals:
            return None

        return UserFinancialSnapshot(
            monthly_income=(
                MoneyAmount(currency=profile.currency, amount=float(profile.monthly_income))
                if profile and profile.monthly_income is not None
                else None
            ),
            recurring_expenses=[item for item in transactions if item.recurring],
            recent_transactions=transactions,
            goals=goals,
            risk_tolerance=profile.risk_tolerance if profile else None,
            preferences=(
                {
                    "employment_status": profile.employment_status,
                    "occupation_category": profile.occupation_category,
                    "income_frequency": profile.income_frequency,
                    "income_stability": profile.income_stability,
                    "household_size": profile.household_size,
                    "dependants": profile.dependants,
                    "housing_status": profile.housing_status,
                    "financial_literacy": profile.financial_literacy,
                    "preferred_language": profile.preferred_language,
                    "accessibility_preferences": profile.accessibility_preferences,
                }
                if profile
                else {}
            ),
        )


class SQLAlchemyFairnessProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_demographics(self, user_id: str) -> ProfileDemographicRecord | None:
        return self.session.get(ProfileDemographicRecord, user_id)

    def get_consent(self, user_id: str) -> ProfileConsentRecord | None:
        return self.session.get(
            ProfileConsentRecord,
            (user_id, FAIRNESS_EVALUATION_PURPOSE),
        )

    def set_consent(self, user_id: str, granted: bool) -> ProfileConsentRecord:
        _ensure_user(self.session, user_id)
        record = self.get_consent(user_id)
        now = datetime.now(UTC)
        if record is None:
            record = ProfileConsentRecord(
                user_id=user_id,
                purpose=FAIRNESS_EVALUATION_PURPOSE,
                consent_version=FAIRNESS_CONSENT_VERSION,
            )
            self.session.add(record)
        record.consent_version = FAIRNESS_CONSENT_VERSION
        record.granted = granted
        record.granted_at = now if granted else record.granted_at
        record.withdrawn_at = None if granted else now
        if not granted:
            demographics = self.get_demographics(user_id)
            if demographics is not None:
                self.session.delete(demographics)
        self.session.flush()
        return record

    def upsert_demographics(
        self, user_id: str, demographics: DemographicUpsert
    ) -> ProfileDemographicRecord:
        consent = self.get_consent(user_id)
        if consent is None or not consent.granted:
            raise PermissionError("Fairness evaluation consent is required")
        record = self.get_demographics(user_id)
        if record is None:
            record = ProfileDemographicRecord(user_id=user_id)
            self.session.add(record)
        for field, value in demographics.model_dump().items():
            setattr(record, field, value)
        _touch_user(self.session, user_id)
        self.session.flush()
        return record


class SQLAlchemyConsentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: str, purpose: str) -> ProfileConsentRecord | None:
        return self.session.get(ProfileConsentRecord, (user_id, purpose))

    def set_durable_memory_consent(
        self, user_id: str, granted: bool
    ) -> ProfileConsentRecord:
        _ensure_user(self.session, user_id)
        record = self.get(user_id, DURABLE_MEMORY_PURPOSE)
        now = datetime.now(UTC)
        if record is None:
            record = ProfileConsentRecord(
                user_id=user_id,
                purpose=DURABLE_MEMORY_PURPOSE,
                consent_version=DURABLE_MEMORY_CONSENT_VERSION,
            )
            self.session.add(record)
        record.consent_version = DURABLE_MEMORY_CONSENT_VERSION
        record.granted = granted
        record.granted_at = now if granted else record.granted_at
        record.withdrawn_at = None if granted else now
        self.session.flush()
        return record


class SQLAlchemyTransactionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    @trace_method
    def _query(
        user_id: str, period_start: date | None = None
    ) -> Select[tuple[TransactionRecord]]:
        query = (
            select(TransactionRecord)
            .where(TransactionRecord.user_id == user_id)
            .order_by(TransactionRecord.occurred_on.desc(), TransactionRecord.created_at.desc())
        )
        if period_start is not None:
            query = query.where(
                TransactionRecord.occurred_on >= period_start,
                TransactionRecord.occurred_on < next_month(period_start),
            )
        return query

    @trace_method
    def list_records(
        self, user_id: str, *, period_start: date | None = None, limit: int = 500
    ) -> list[TransactionRecord]:
        return list(self.session.scalars(self._query(user_id, period_start).limit(limit)))

    @trace_method
    def list_for_user(self, user_id: str) -> list[Transaction]:
        return [
            Transaction(
                description=record.description,
                category=record.category,
                amount=MoneyAmount(currency=record.currency, amount=float(record.amount)),
                occurred_on=record.occurred_on.isoformat(),
                recurring=record.recurring,
            )
            for record in self.list_records(user_id) if record.transaction_type == "expense"
        ]

    def create(self, user_id: str, transaction: TransactionCreate) -> TransactionRecord:
        _ensure_user(self.session, user_id)
        record = TransactionRecord(
            user_id=user_id,
            description=transaction.description,
            category=transaction.category,
            amount=transaction.amount.amount,
            currency=transaction.amount.currency,
            occurred_on=transaction.occurred_on,
            recurring=transaction.recurring,
            transaction_type=transaction.transaction_type,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def update(
        self, user_id: str, transaction_id: UUID, transaction: TransactionCreate
    ) -> TransactionRecord | None:
        from app.services.budget_reconciliation import guard_transaction
        guard_transaction(self.session, user_id, transaction_id)
        record = self.session.scalar(
            select(TransactionRecord).where(
                TransactionRecord.id == transaction_id,
                TransactionRecord.user_id == user_id,
            )
        )
        if record is None:
            return None
        record.description = transaction.description
        record.category = transaction.category
        record.amount = transaction.amount.amount
        record.currency = transaction.amount.currency
        record.occurred_on = transaction.occurred_on
        record.recurring = transaction.recurring
        record.transaction_type = transaction.transaction_type
        _touch_user(self.session, user_id)
        self.session.flush()
        return record

    def delete(self, user_id: str, transaction_id: object) -> bool:
        from app.services.budget_reconciliation import guard_transaction
        guard_transaction(self.session, user_id, transaction_id)
        record = self.session.scalar(
            select(TransactionRecord).where(
                TransactionRecord.id == transaction_id,
                TransactionRecord.user_id == user_id,
            )
        )
        if record is None:
            return False
        self.session.delete(record)
        _touch_user(self.session, user_id)
        self.session.flush()
        return True


class SQLAlchemyGoalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @trace_method
    def list_records(self, user_id: str) -> list[FinancialGoalRecord]:
        query = (
            select(FinancialGoalRecord)
            .where(FinancialGoalRecord.user_id == user_id)
            .order_by(FinancialGoalRecord.created_at.desc())
        )
        return list(self.session.scalars(query))

    @trace_method
    def list_for_user(self, user_id: str) -> list[FinancialGoal]:
        return [
            FinancialGoal(
                name=record.name,
                target_amount=MoneyAmount(
                    currency=record.currency, amount=float(record.target_amount)
                ),
                current_amount=MoneyAmount(
                    currency=record.currency, amount=float(record.current_amount)
                ),
                target_months=record.target_months,
            )
            for record in self.list_records(user_id)
        ]

    def create(self, user_id: str, goal: GoalCreate) -> FinancialGoalRecord:
        _ensure_user(self.session, user_id)
        if goal.current_amount.currency != goal.target_amount.currency:
            raise ValueError("Goal amounts must use the same currency")
        record = FinancialGoalRecord(
            user_id=user_id,
            name=goal.name,
            target_amount=goal.target_amount.amount,
            current_amount=goal.current_amount.amount,
            currency=goal.target_amount.currency,
            target_months=goal.target_months,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def update(
        self, user_id: str, goal_id: UUID, goal: GoalCreate
    ) -> FinancialGoalRecord | None:
        record = self.session.scalar(
            select(FinancialGoalRecord).where(
                FinancialGoalRecord.id == goal_id,
                FinancialGoalRecord.user_id == user_id,
            )
        )
        if record is None:
            return None
        if goal.current_amount.currency != goal.target_amount.currency:
            raise ValueError("Goal amounts must use the same currency")
        record.name = goal.name
        record.target_amount = goal.target_amount.amount
        record.current_amount = goal.current_amount.amount
        record.currency = goal.target_amount.currency
        record.target_months = goal.target_months
        _touch_user(self.session, user_id)
        self.session.flush()
        return record

    def delete(self, user_id: str, goal_id: object) -> bool:
        record = self.session.scalar(
            select(FinancialGoalRecord).where(
                FinancialGoalRecord.id == goal_id,
                FinancialGoalRecord.user_id == user_id,
            )
        )
        if record is None:
            return False
        self.session.delete(record)
        _touch_user(self.session, user_id)
        self.session.flush()
        return True


class SQLAlchemyBudgetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(
        self, user_id: str, period_start: date, *, for_update: bool = False
    ) -> MonthlyBudgetRecord | None:
        if for_update:
            # Serialize absent-row creation as well as edits with the same lock as upsert.
            _lock_user_lifecycle(self.session, user_id)
        query = (
            select(MonthlyBudgetRecord)
            .options(selectinload(MonthlyBudgetRecord.categories))
            .where(
                MonthlyBudgetRecord.user_id == user_id,
                MonthlyBudgetRecord.period_start == period_start,
            )
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def upsert(self, user_id: str, budget: BudgetUpsert) -> MonthlyBudgetRecord:
        from app.services.budget_constraints import constraint_questions
        questions = constraint_questions(self.session, user_id, budget.period_start,
            {item.category: item.limit_amount for item in budget.categories}, budget.planning)
        if questions:
            raise ValueError(" ".join(questions))
        _ensure_user(self.session, user_id)
        record = self.get(user_id, budget.period_start, for_update=True)
        from app.services.budget_capture import _snapshot
        from app.services.budget_history import record_version
        previous = _snapshot(record) if record else None
        if record is None:
            record = MonthlyBudgetRecord(
                user_id=user_id,
                period_start=budget.period_start,
                currency=budget.currency,
            )
            self.session.add(record)
            self.session.flush()
        else:
            record.currency = budget.currency

        record.planning = budget.planning.model_dump(mode="json") if budget.planning else None
        existing = {item.category: item for item in record.categories}
        requested = {item.category for item in budget.categories}
        for category, category_record in existing.items():
            if category not in requested:
                record.categories.remove(category_record)
                self.session.delete(category_record)

        for category in budget.categories:
            category_record = existing.get(category.category)
            if category_record is None:
                category_record = BudgetCategoryRecord(
                    budget=record,
                    category=category.category,
                    limit_amount=category.limit_amount,
                )
                self.session.add(category_record)
            else:
                category_record.limit_amount = category.limit_amount
        self.session.flush()
        record_version(self.session, user_id, budget.period_start, previous, _snapshot(record))
        return record

    def spending_by_category(self, user_id: str, period_start: date, *, currency: str | None = None) -> dict[str, float]:
        query = (
            select(TransactionRecord.category, func.sum(TransactionRecord.amount))
            .where(
                TransactionRecord.user_id == user_id,
                TransactionRecord.occurred_on >= period_start,
                TransactionRecord.transaction_type == "expense",
                TransactionRecord.occurred_on < next_month(period_start),
            )
            .group_by(TransactionRecord.category)
        )
        if currency is not None:
            query = query.where(TransactionRecord.currency == currency)
        totals = {category: float(amount) for category, amount in self.session.execute(query)}
        if currency in {None, "SGD"}:
            from app.services.budget_reconciliation import refund_offsets
            for name, amount in refund_offsets(self.session, user_id, period_start).items():
                totals[name] = round(totals.get(name, 0) - amount / 100, 2)
        return totals

    def review_spending(self, user_id: str, period_start: date, through: date) -> list[dict]:
        """Owned SGD aggregates through a fixed cutoff; no transaction descriptions leave storage."""
        query = select(
            TransactionRecord.category, TransactionRecord.recurring,
            func.sum(TransactionRecord.amount), func.count(TransactionRecord.id),
            func.count(func.distinct(TransactionRecord.occurred_on)),
        ).where(
            TransactionRecord.user_id == user_id,
            TransactionRecord.currency == "SGD",
            TransactionRecord.occurred_on >= period_start,
                TransactionRecord.transaction_type == "expense",
            TransactionRecord.occurred_on < next_month(period_start),
            TransactionRecord.occurred_on <= through,
        ).group_by(TransactionRecord.category, TransactionRecord.recurring)
        rows = [{"category": category, "recurring": recurring, "amount": str(amount),
                 "count": count, "activity_days": days}
                for category, recurring, amount, count, days in self.session.execute(query)]
        from app.services.budget_reconciliation import refund_offsets
        rows.extend({"category": name, "recurring": True, "amount": str(-amount/100), "count": 0, "activity_days": 0, "refund_offset": True}
                    for name, amount in refund_offsets(self.session, user_id, period_start, through).items())
        return rows

    def transaction_count(self, user_id: str, period_start: date, *, currency: str | None = None) -> int:
        query = select(func.count(TransactionRecord.id)).where(
            TransactionRecord.user_id == user_id,
            TransactionRecord.occurred_on >= period_start,
                TransactionRecord.transaction_type == "expense",
            TransactionRecord.occurred_on < next_month(period_start),
        )
        if currency is not None:
            query = query.where(TransactionRecord.currency == currency)
        return int(self.session.scalar(query) or 0)
    
    def get_transactions_in_range(
        self, user_id: str, start_date: date, end_date: date, *, currency: str | None = None
    ) -> list[TransactionRecord]:
        """Get all transactions for a user in a date range."""
        query = select(TransactionRecord).where(
            TransactionRecord.user_id == user_id,
            TransactionRecord.occurred_on >= start_date,
                TransactionRecord.transaction_type == "expense",
            TransactionRecord.occurred_on <= end_date,
        ).order_by(TransactionRecord.occurred_on)
        if currency is not None:
            query = query.where(TransactionRecord.currency == currency)
        return list(self.session.scalars(query))


class SQLAlchemyChatRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @trace_method
    def context_snapshot(self, user_id: str, session_id: str) -> tuple[bool, int, list[dict]]:
        owner = self.session.scalar(
            select(ChatSessionRecord.user_id).where(ChatSessionRecord.id == session_id)
        )
        if owner is None:
            return False, 0, []
        if owner != user_id:
            raise PermissionError("Conversation not found")
        messages = list(self.session.scalars(
            select(ChatMessageRecord)
            .options(selectinload(ChatMessageRecord.orchestration_trace))
            .where(ChatMessageRecord.session_id == session_id)
            .order_by(ChatMessageRecord.position.desc()).limit(8)
        ))
        context = []
        for message in reversed(messages):
            content = message.content
            if message.role == "assistant":
                trace = message.orchestration_trace
                if trace is None or trace.blocked:
                    content = "The previous answer is unavailable or was withheld. Ask for clarification."
            context.append({"role": message.role, "content": content[:1500]})
        return True, messages[0].position if messages else 0, context

    @trace_method
    def list_for_user(self, user_id: str) -> list[ChatSessionRecord]:
        query = (
            select(ChatSessionRecord)
            .options(selectinload(ChatSessionRecord.messages))
            .where(ChatSessionRecord.user_id == user_id)
            .order_by(ChatSessionRecord.updated_at.desc(), ChatSessionRecord.created_at.desc())
        )
        return list(self.session.scalars(query))

    @trace_method
    def get(self, user_id: str, session_id: str) -> ChatSessionRecord | None:
        query = (
            select(ChatSessionRecord)
            .options(
                selectinload(ChatSessionRecord.messages).selectinload(
                    ChatMessageRecord.orchestration_trace
                )
            )
            .where(
                ChatSessionRecord.id == session_id,
                ChatSessionRecord.user_id == user_id,
            )
        )
        return self.session.scalar(query)

    @trace_method
    def get_for_update(
        self, user_id: str, session_id: str
    ) -> ChatSessionRecord | None:
        # Keep lock order consistent with budget writes and profile deletion.
        _lock_user_lifecycle(self.session, user_id)
        query = (
            select(ChatSessionRecord)
            .options(selectinload(ChatSessionRecord.messages))
            .where(
                ChatSessionRecord.id == session_id,
                ChatSessionRecord.user_id == user_id,
            )
            .with_for_update()
        )
        return self.session.scalar(query)

    @trace_method
    def id_exists(self, session_id: str) -> bool:
        return self.session.get(ChatSessionRecord, session_id) is not None

    @trace_method
    def create(self, user_id: str, session_id: str, title: str) -> ChatSessionRecord:
        _ensure_user(self.session, user_id)
        record = ChatSessionRecord(id=session_id, user_id=user_id, title=title)
        self.session.add(record)
        self.session.flush()
        return record

    def rename(
        self, user_id: str, session_id: str, title: str
    ) -> ChatSessionRecord | None:
        record = self.get(user_id, session_id)
        if record is None:
            return None
        record.title = title
        _touch_user(self.session, user_id)
        self.session.flush()
        return record

    def delete(self, user_id: str, session_id: str) -> bool:
        record = self.get(user_id, session_id)
        if record is None:
            return False
        _touch_user(self.session, user_id)
        self.session.delete(record)
        self.session.flush()
        SQLAlchemyUserRepository(self.session).delete_if_empty(user_id)
        return True

    @trace_method
    def append_message(
        self,
        chat_session: ChatSessionRecord,
        role: str,
        content: str,
        sources: list[dict[str, Any]] | None = None,
    ) -> ChatMessageRecord:
        message = ChatMessageRecord(
            chat_session=chat_session,
            role=role,
            content=content,
            sources=sources or [],
            position=len(chat_session.messages) + 1,
        )
        self.session.add(message)
        chat_session.updated_at = datetime.now(UTC)
        _touch_user(self.session, chat_session.user_id)
        self.session.flush()
        return message


class SQLAlchemyOrchestrationTraceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @trace_method
    def create(
        self,
        *,
        trace_id: str,
        session_id: str,
        assistant_message_id: UUID | None,
        selected_agents: list[str],
        agent_results: list[dict[str, Any]],
        audit: dict[str, Any],
        blocked: bool,
    ) -> OrchestrationTraceRecord:
        record = OrchestrationTraceRecord(
            trace_id=trace_id,
            session_id=session_id,
            assistant_message_id=assistant_message_id,
            selected_agents=selected_agents,
            agent_results=agent_results,
            audit=audit,
            blocked=blocked,
            status="blocked" if blocked else "completed",
            model_provider=audit.get("model_provider"),
            model_id=audit.get("model_id"),
            prompt_set_version=audit.get("prompt_set_version"),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_for_user(self, user_id: str, *, status: str | None, limit: int, offset: int):
        query = (
            select(OrchestrationTraceRecord, ChatSessionRecord.title)
            .join(ChatSessionRecord, ChatSessionRecord.id == OrchestrationTraceRecord.session_id)
            .options(load_only(
                OrchestrationTraceRecord.trace_id, OrchestrationTraceRecord.session_id,
                OrchestrationTraceRecord.status, OrchestrationTraceRecord.selected_agents,
                OrchestrationTraceRecord.created_at, OrchestrationTraceRecord.finished_at,
                OrchestrationTraceRecord.error_code,
            ))
            .where(ChatSessionRecord.user_id == user_id)
            .order_by(OrchestrationTraceRecord.created_at.desc(), OrchestrationTraceRecord.trace_id.desc())
            .offset(offset).limit(limit + 1)
        )
        if status is not None:
            query = query.where(OrchestrationTraceRecord.status == status)
        return self.session.execute(query).all()

    def get_for_user(
        self,
        user_id: str,
        trace_id: str,
    ) -> OrchestrationTraceRecord | None:
        query = (
            select(OrchestrationTraceRecord)
            .join(
                ChatSessionRecord,
                ChatSessionRecord.id == OrchestrationTraceRecord.session_id,
            )
            .where(
                OrchestrationTraceRecord.trace_id == trace_id,
                ChatSessionRecord.user_id == user_id,
            )
        )
        return self.session.scalar(query)

    def delete_for_user(self, user_id: str, trace_id: str) -> bool:
        record = self.get_for_user(user_id, trace_id)
        if record is None:
            return False
        self._sanitize_blocked_assistant_message(record)
        self.session.delete(record)
        self.session.flush()
        return True

    def mark_abandoned(self, now: datetime, *, user_id: str | None = None) -> int:
        """Deadline exceeds the bounded HTTP call, including persistence grace time."""
        query = update(OrchestrationTraceRecord).where(
            OrchestrationTraceRecord.status == "running",
            OrchestrationTraceRecord.deadline_at < now,
        )
        if user_id is not None:
            query = query.where(OrchestrationTraceRecord.session_id.in_(
                select(ChatSessionRecord.id).where(ChatSessionRecord.user_id == user_id)
            ))
        result = self.session.execute(
            query.values(status="abandoned", error_code="RUN_ABANDONED", finished_at=now)
            .execution_options(synchronize_session="fetch")
        )
        return int(result.rowcount or 0)

    def delete_expired(self, cutoff: datetime) -> int:
        self.mark_abandoned(datetime.now(UTC))
        expired = OrchestrationTraceRecord.created_at < cutoff
        language = OrchestrationTraceRecord.audit["response_language"].as_string()
        for response_language, language_filter in (
            ("Chinese", language == "Chinese"),
            ("English", or_(language.is_(None), language != "Chinese")),
        ):
            blocked_message_ids = select(
                OrchestrationTraceRecord.assistant_message_id
            ).where(expired, OrchestrationTraceRecord.blocked.is_(True), language_filter)
            self.session.execute(
                update(ChatMessageRecord)
                .where(
                    ChatMessageRecord.id.in_(blocked_message_ids),
                    ChatMessageRecord.role == "assistant",
                )
                .values(
                    content=case(
                        *[
                            (
                                ChatMessageRecord.content.in_((english, chinese)),
                                chinese if response_language == "Chinese" else english,
                            )
                            for english, chinese in SAFE_REFUSAL_TEMPLATES
                        ],
                        else_=blocked_response_answer(response_language=response_language),
                    ),
                    sources=[],
                )
                .execution_options(synchronize_session="fetch")
            )
        result = self.session.execute(delete(OrchestrationTraceRecord).where(expired))
        return int(getattr(result, "rowcount", 0) or 0)

    def _sanitize_blocked_assistant_message(
        self, record: OrchestrationTraceRecord
    ) -> None:
        message = record.assistant_message
        if record.blocked and message is not None and message.role == "assistant":
            message.content = blocked_response_answer(
                response_language=record.audit.get("response_language", "English"),
                answer=message.content,
            )
            message.sources = []


class SQLAlchemyDataLifecycleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def delete_expired_chat_sessions(self, cutoff: datetime) -> int:
        records = list(
            self.session.scalars(
                select(ChatSessionRecord).where(ChatSessionRecord.updated_at < cutoff)
            )
        )
        for record in records:
            self.session.delete(record)
        self.session.flush()
        return len(records)

    def delete_expired_synthetic_users(
        self, cutoff: datetime, prefixes: tuple[str, ...]
    ) -> int:
        if not prefixes:
            return 0
        records = list(
            self.session.scalars(
                select(UserRecord).where(
                    UserRecord.owner_issuer.is_(None),
                    UserRecord.owner_subject.is_(None),
                    UserRecord.last_activity_at < cutoff,
                    or_(*(UserRecord.id.startswith(prefix) for prefix in prefixes)),
                )
            )
        )
        for record in records:
            self.session.delete(record)
        self.session.flush()
        return len(records)
