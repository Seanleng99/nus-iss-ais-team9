from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserRecord(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_owner_identity", "owner_issuer", "owner_subject"),
        CheckConstraint(
            "(owner_issuer IS NULL) = (owner_subject IS NULL)",
            name="owner_identity_complete",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_issuer: Mapped[str | None] = mapped_column(String(512))
    owner_subject: Mapped[str | None] = mapped_column(String(255))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    profile: Mapped["FinancialProfileRecord | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    demographics: Mapped["ProfileDemographicRecord | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    consents: Mapped[list["ProfileConsentRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["TransactionRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    goals: Mapped[list["FinancialGoalRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    budgets: Mapped[list["MonthlyBudgetRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSessionRecord"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class FinancialProfileRecord(TimestampMixin, Base):
    __tablename__ = "financial_profiles"
    __table_args__ = (
        CheckConstraint(
            "monthly_income IS NULL OR monthly_income >= 0",
            name="monthly_income_non_negative",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    monthly_income: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    risk_tolerance: Mapped[str | None] = mapped_column(String(32))
    employment_status: Mapped[str | None] = mapped_column(String(32))
    occupation_category: Mapped[str | None] = mapped_column(String(64))
    income_frequency: Mapped[str | None] = mapped_column(String(32))
    income_stability: Mapped[str | None] = mapped_column(String(32))
    household_size: Mapped[int | None] = mapped_column()
    dependants: Mapped[int | None] = mapped_column()
    housing_status: Mapped[str | None] = mapped_column(String(32))
    financial_literacy: Mapped[str | None] = mapped_column(String(32))
    preferred_language: Mapped[str | None] = mapped_column(String(32))
    accessibility_preferences: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    user: Mapped[UserRecord] = relationship(back_populates="profile")


class ProfileDemographicRecord(TimestampMixin, Base):
    __tablename__ = "profile_demographics"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    age_band: Mapped[str | None] = mapped_column(String(32))
    gender_identity: Mapped[str | None] = mapped_column(String(64))
    race_ethnicity: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    nationality_residency: Mapped[str | None] = mapped_column(String(64))
    disability_status: Mapped[str | None] = mapped_column(String(64))
    marital_status: Mapped[str | None] = mapped_column(String(32))
    residential_region: Mapped[str | None] = mapped_column(String(64))
    user: Mapped[UserRecord] = relationship(back_populates="demographics")


class ProfileConsentRecord(TimestampMixin, Base):
    __tablename__ = "profile_consents"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[str] = mapped_column(String(64), primary_key=True)
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[UserRecord] = relationship(back_populates="consents")


class TransactionRecord(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        Index("ix_transactions_user_occurred", "user_id", "occurred_on"),
        Index("ix_transactions_user_category", "user_id", "category"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user: Mapped[UserRecord] = relationship(back_populates="transactions")


class FinancialGoalRecord(TimestampMixin, Base):
    __tablename__ = "financial_goals"
    __table_args__ = (
        CheckConstraint("target_amount >= 0", name="target_amount_non_negative"),
        CheckConstraint("current_amount >= 0", name="current_amount_non_negative"),
        CheckConstraint(
            "target_months > 0 AND target_months <= 600", name="target_months_range"
        ),
        Index("ix_financial_goals_user", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    current_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal(0), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    target_months: Mapped[int] = mapped_column(nullable=False)
    user: Mapped[UserRecord] = relationship(back_populates="goals")


class MonthlyBudgetRecord(TimestampMixin, Base):
    __tablename__ = "monthly_budgets"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_start", name="uq_monthly_budgets_user_period"
        ),
        Index("ix_monthly_budgets_user_period", "user_id", "period_start"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="SGD", nullable=False)
    user: Mapped[UserRecord] = relationship(back_populates="budgets")
    categories: Mapped[list["BudgetCategoryRecord"]] = relationship(
        back_populates="budget", cascade="all, delete-orphan"
    )


class BudgetCategoryRecord(TimestampMixin, Base):
    __tablename__ = "budget_categories"
    __table_args__ = (
        CheckConstraint("limit_amount >= 0", name="limit_amount_non_negative"),
        UniqueConstraint(
            "budget_id", "category", name="uq_budget_categories_budget_category"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("monthly_budgets.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    budget: Mapped[MonthlyBudgetRecord] = relationship(back_populates="categories")


class ChatSessionRecord(TimestampMixin, Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    pending_budget: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user: Mapped[UserRecord] = relationship(back_populates="chat_sessions")
    traces: Mapped[list["OrchestrationTraceRecord"]] = relationship(
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["ChatMessageRecord"]] = relationship(
        back_populates="chat_session",
        cascade="all, delete-orphan",
        order_by="ChatMessageRecord.position",
    )


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="chat_message_role"),
        CheckConstraint("position > 0", name="chat_message_position_positive"),
        UniqueConstraint("session_id", "position", name="uq_chat_messages_session_position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    position: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    chat_session: Mapped[ChatSessionRecord] = relationship(back_populates="messages")
    orchestration_trace: Mapped["OrchestrationTraceRecord | None"] = relationship(
        back_populates="assistant_message",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
        passive_deletes=True,
    )


class OrchestrationTraceRecord(Base):
    __tablename__ = "orchestration_traces"
    __table_args__ = (
        Index("ix_orchestration_traces_session_created", "session_id", "created_at"),
        CheckConstraint("status IN ('running', 'completed', 'blocked', 'failed', 'timed_out', 'abandoned')", name="run_status"),
    )

    trace_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    selected_agents: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    agent_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    audit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(64))
    model_id: Mapped[str | None] = mapped_column(String(256))
    prompt_set_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="completed", server_default="completed", nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(128))
    assistant_message: Mapped[ChatMessageRecord | None] = relationship(
        back_populates="orchestration_trace"
    )
