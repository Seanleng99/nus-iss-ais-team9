from datetime import date

from coach_math.budget_scope import BudgetScope
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.conversation_context import SessionField


class TurnQueries(BaseModel):
    """Read-only portions of the private service's validated turn decision."""

    model_config = ConfigDict(extra="ignore")
    budget_status_query: bool = Field(default=False, strict=True)
    budget_scope: BudgetScope | None = None
    budget_scope_unclear: bool = Field(default=False, strict=True)
    budget_status_period_start: date | None = None
    missing_fields: list[SessionField] = Field(default_factory=list, max_length=7)
    memory_question: bool = Field(default=False, strict=True)
    memory_fields: list[SessionField] = Field(default_factory=list, max_length=7)

    @field_validator("budget_status_period_start")
    @classmethod
    def first_of_month(cls, value):
        if value is not None and value.day != 1:
            raise ValueError("Budget query periods must start on the first day")
        return value
