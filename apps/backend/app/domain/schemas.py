from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentName(StrEnum):
    SPENDING = "spending"
    BUDGET = "budget"
    GOAL_STRATEGY = "goal_strategy"
    INVESTMENT_EDUCATION = "investment_education"
    RISK_COMPLIANCE = "risk_compliance"


class MoneyAmount(BaseModel):
    currency: str = "SGD"
    amount: float = Field(ge=0)


class Transaction(BaseModel):
    description: str
    category: str
    amount: MoneyAmount
    occurred_on: str


class FinancialGoal(BaseModel):
    name: str
    target_amount: MoneyAmount
    current_amount: MoneyAmount = Field(default_factory=lambda: MoneyAmount(amount=0))
    target_months: int = Field(gt=0, le=600)


class UserFinancialSnapshot(BaseModel):
    monthly_income: MoneyAmount | None = None
    recurring_expenses: list[Transaction] = Field(default_factory=list)
    recent_transactions: list[Transaction] = Field(default_factory=list)
    goals: list[FinancialGoal] = Field(default_factory=list)
    risk_tolerance: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)


class CoachRequest(BaseModel):
    user_id: str
    session_id: str
    message: str = Field(min_length=1, max_length=5000)
    snapshot: UserFinancialSnapshot = Field(default_factory=UserFinancialSnapshot)
    requested_agents: list[AgentName] | None = None

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        return value.strip()


class AgentResult(BaseModel):
    agent: AgentName
    summary: str
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    data: dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    policy_notes: list[str] = Field(default_factory=list)


class CoachResponse(BaseModel):
    session_id: str
    selected_agents: list[AgentName]
    answer: str
    agent_results: list[AgentResult]
    disclaimers: list[str]
    audit: dict[str, Any]
    blocked: bool = False
