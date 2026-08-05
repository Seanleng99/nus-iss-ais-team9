from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.schemas import MoneyAmount, UserFinancialSnapshot


class ProfileUpsert(BaseModel):
    monthly_income: MoneyAmount | None = None
    risk_tolerance: str | None = Field(default=None, max_length=32)
    preferences: dict[str, Any] = Field(default_factory=dict)


class ProfileResponse(ProfileUpsert):
    user_id: str


class TransactionCreate(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=64)
    amount: MoneyAmount
    occurred_on: date
    recurring: bool = False

    @model_validator(mode="after")
    def normalize_text(self) -> "TransactionCreate":
        self.description = self.description.strip()
        self.category = self.category.strip().lower()
        if not self.description or not self.category:
            raise ValueError("Transaction description and category are required")
        return self


class TransactionResponse(TransactionCreate):
    id: UUID


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: MoneyAmount
    current_amount: MoneyAmount = Field(default_factory=lambda: MoneyAmount(amount=0))
    target_months: int = Field(gt=0, le=600)

    @model_validator(mode="after")
    def normalize_name(self) -> "GoalCreate":
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Goal name is required")
        return self


class GoalResponse(GoalCreate):
    id: UUID


class SnapshotResponse(UserFinancialSnapshot):
    user_id: str


class BudgetCategoryInput(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    limit_amount: float = Field(ge=0)


class BudgetUpsert(BaseModel):
    period_start: date
    currency: str = Field(default="SGD", pattern=r"^[A-Z]{3}$")
    categories: list[BudgetCategoryInput] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_period_and_categories(self) -> "BudgetUpsert":
        if self.period_start.day != 1:
            raise ValueError("Budget period_start must be the first day of a month")
        normalized = [item.category.strip().lower() for item in self.categories]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Budget categories must be unique")
        for item, category in zip(self.categories, normalized, strict=True):
            item.category = category
        return self


class BudgetCategoryResponse(BudgetCategoryInput):
    spent_amount: float
    remaining_amount: float


class BudgetResponse(BaseModel):
    period_start: date
    currency: str
    total_limit: float
    total_spent: float
    total_remaining: float
    categories: list[BudgetCategoryResponse]


class GoalProgressResponse(BaseModel):
    id: UUID
    name: str
    current_amount: float
    target_amount: float
    progress_percent: float
    monthly_required: float


class DashboardResponse(BaseModel):
    period_start: date
    currency: str
    monthly_income: float
    total_spent: float
    available_balance: float
    savings_rate_percent: float
    budget: BudgetResponse | None
    category_spending: dict[str, float]
    goals: list[GoalProgressResponse]
    transaction_count: int
