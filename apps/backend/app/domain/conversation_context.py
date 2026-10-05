"""Untrusted AI conversation metadata validated at the owned-chat boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SessionField = Literal[
    "monthly_income", "monthly_expenses", "goal_target_amount", "goal_current_amount",
    "goal_name", "goal_target_months", "budget_period_start",
]
Topic = Literal["spending", "budget", "goal_strategy", "investment_education"]


class AttributedObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["fact", "preference", "objective", "discussion"]
    field: SessionField | None = None
    value: str | None = Field(default=None, min_length=1, max_length=120)
    source_quote: str = Field(min_length=1, max_length=240)
    source_position: int = Field(ge=1)
    attribution: Literal["self", "general", "other", "hypothetical", "quoted"]
    cadence: Literal["monthly", "once", "unknown"] = "unknown"
    topics: list[Topic] = Field(default_factory=list, max_length=4)


class ConversationReferent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=160)
    agent: Topic
    education_topics: list[str] = Field(default_factory=list, max_length=12)
    source_quote: str = Field(min_length=1, max_length=240)
    source_position: int = Field(ge=1)
    option_index: int | None = Field(default=None, ge=1, le=12)
