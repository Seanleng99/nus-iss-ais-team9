"""Serializable budgeting method contract; categories are classified only by the user."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

METHOD_LABELS = {
    "flexible": "Flexible category plan",
    "50_30_20": "50/30/20",
    "80_20": "80/20",
    "zero_based": "Zero-based",
    "pay_yourself_first": "Savings first",
    "custom": "Custom percentages",
}


class Percentages(BaseModel):
    model_config = ConfigDict(extra="forbid")
    needs: float = Field(ge=0, le=100, multiple_of=0.01, allow_inf_nan=False)
    wants: float = Field(ge=0, le=100, multiple_of=0.01, allow_inf_nan=False)
    savings: float = Field(ge=0, le=100, multiple_of=0.01, allow_inf_nan=False)


class BudgetMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["flexible", "50_30_20", "80_20", "zero_based", "pay_yourself_first", "custom"] = (
        "flexible"
    )
    percentages: Percentages | None = None
    category_groups: dict[str, Literal["needs", "wants"]] = Field(
        default_factory=dict, max_length=50
    )

    @field_validator("category_groups")
    @classmethod
    def normalize_groups(cls, value):
        normalized = {" ".join(key.split()).lower(): group for key, group in value.items()}
        if len(normalized) != len(value) or any(not key or len(key) > 64 for key in normalized):
            raise ValueError("Use unique category names of 1 to 64 characters")
        return normalized

    def questions(self, categories):
        result = []
        if self.name == "custom":
            if self.percentages is None:
                result.append(
                    "What needs, wants and savings percentages should be used? They must total 100%."
                )
            elif (
                sum(Decimal(str(value)) for value in self.percentages.model_dump().values()) != 100
            ):
                result.append("Custom needs, wants and savings percentages must total 100%.")
        elif self.percentages is not None:
            result.append(
                "Custom percentages require the custom method; remove them or select custom."
            )
        if self.name in {"50_30_20", "custom"}:
            missing = [name for name in categories if name not in self.category_groups]
            if missing:
                result.append(
                    "Classify these categories as needs or wants: " + ", ".join(missing) + "."
                )
        return result
