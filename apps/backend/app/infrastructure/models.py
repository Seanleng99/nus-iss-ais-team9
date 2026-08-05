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

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    profile: Mapped["FinancialProfileRecord | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
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
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    user: Mapped[UserRecord] = relationship(back_populates="profile")


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
