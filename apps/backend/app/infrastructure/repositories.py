from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.financial_schemas import (
    BudgetUpsert,
    DemographicUpsert,
    GoalCreate,
    ProfileUpsert,
    TransactionCreate,
)
from app.domain.schemas import FinancialGoal, MoneyAmount, Transaction, UserFinancialSnapshot
from app.infrastructure.models import (
    BudgetCategoryRecord,
    FinancialGoalRecord,
    FinancialProfileRecord,
    MonthlyBudgetRecord,
    ProfileConsentRecord,
    ProfileDemographicRecord,
    TransactionRecord,
    UserRecord,
)

FAIRNESS_EVALUATION_PURPOSE = "fairness_evaluation"
FAIRNESS_CONSENT_VERSION = "1.0"


def _ensure_user(session: Session, user_id: str) -> UserRecord:
    user = session.get(UserRecord, user_id)
    if user is None:
        user = UserRecord(id=user_id)
        session.add(user)
        session.flush()
    return user


def next_month(period_start: date) -> date:
    if period_start.month == 12:
        return date(period_start.year + 1, 1, 1)
    return date(period_start.year, period_start.month + 1, 1)


class SQLAlchemyUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_profile(self, user_id: str) -> FinancialProfileRecord | None:
        return self.session.get(FinancialProfileRecord, user_id)

    def list_profiles(self) -> list[FinancialProfileRecord]:
        query = select(FinancialProfileRecord).order_by(
            FinancialProfileRecord.updated_at.desc(),
            FinancialProfileRecord.user_id,
        )
        return list(self.session.scalars(query))

    def exists(self, user_id: str) -> bool:
        return self.session.get(UserRecord, user_id) is not None

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

    def get_financial_snapshot(self, user_id: str) -> UserFinancialSnapshot | None:
        if self.session.get(UserRecord, user_id) is None:
            return None

        profile = self.get_profile(user_id)
        transaction_repository = SQLAlchemyTransactionRepository(self.session)
        goal_repository = SQLAlchemyGoalRepository(self.session)
        transactions = transaction_repository.list_for_user(user_id)

        return UserFinancialSnapshot(
            monthly_income=(
                MoneyAmount(currency=profile.currency, amount=float(profile.monthly_income))
                if profile and profile.monthly_income is not None
                else None
            ),
            recurring_expenses=[item for item in transactions if item.recurring],
            recent_transactions=transactions,
            goals=goal_repository.list_for_user(user_id),
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
        self.session.flush()
        return record


class SQLAlchemyTransactionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
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

    def list_records(
        self, user_id: str, *, period_start: date | None = None, limit: int = 500
    ) -> list[TransactionRecord]:
        return list(self.session.scalars(self._query(user_id, period_start).limit(limit)))

    def list_for_user(self, user_id: str) -> list[Transaction]:
        return [
            Transaction(
                description=record.description,
                category=record.category,
                amount=MoneyAmount(currency=record.currency, amount=float(record.amount)),
                occurred_on=record.occurred_on.isoformat(),
                recurring=record.recurring,
            )
            for record in self.list_records(user_id)
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
        )
        self.session.add(record)
        self.session.flush()
        return record

    def update(
        self, user_id: str, transaction_id: UUID, transaction: TransactionCreate
    ) -> TransactionRecord | None:
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
        self.session.flush()
        return record

    def delete(self, user_id: str, transaction_id: object) -> bool:
        record = self.session.scalar(
            select(TransactionRecord).where(
                TransactionRecord.id == transaction_id,
                TransactionRecord.user_id == user_id,
            )
        )
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True


class SQLAlchemyGoalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_records(self, user_id: str) -> list[FinancialGoalRecord]:
        query = (
            select(FinancialGoalRecord)
            .where(FinancialGoalRecord.user_id == user_id)
            .order_by(FinancialGoalRecord.created_at.desc())
        )
        return list(self.session.scalars(query))

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
        self.session.flush()
        return True


class SQLAlchemyBudgetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: str, period_start: date) -> MonthlyBudgetRecord | None:
        query = (
            select(MonthlyBudgetRecord)
            .options(selectinload(MonthlyBudgetRecord.categories))
            .where(
                MonthlyBudgetRecord.user_id == user_id,
                MonthlyBudgetRecord.period_start == period_start,
            )
        )
        return self.session.scalar(query)

    def upsert(self, user_id: str, budget: BudgetUpsert) -> MonthlyBudgetRecord:
        _ensure_user(self.session, user_id)
        record = self.get(user_id, budget.period_start)
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
        return record

    def spending_by_category(self, user_id: str, period_start: date) -> dict[str, float]:
        query = (
            select(TransactionRecord.category, func.sum(TransactionRecord.amount))
            .where(
                TransactionRecord.user_id == user_id,
                TransactionRecord.occurred_on >= period_start,
                TransactionRecord.occurred_on < next_month(period_start),
            )
            .group_by(TransactionRecord.category)
        )
        return {category: float(amount) for category, amount in self.session.execute(query)}

    def transaction_count(self, user_id: str, period_start: date) -> int:
        query = select(func.count(TransactionRecord.id)).where(
            TransactionRecord.user_id == user_id,
            TransactionRecord.occurred_on >= period_start,
            TransactionRecord.occurred_on < next_month(period_start),
        )
        return int(self.session.scalar(query) or 0)
