from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.telemetry import trace_method
from app.domain.schemas import (
    AgentName,
    MoneyAmount,
    SourceCitation,
    UserFinancialSnapshot,
    blocked_agent_rationale,
    blocked_response_answer,
    normalize_response_language,
    sanitize_blocked_agent_results,
)

EmploymentStatus = Literal[
    "employed", "self-employed", "student", "unemployed", "retired", "prefer not to say"
]
OccupationCategory = Literal[
    "business and administration",
    "education",
    "engineering and technology",
    "healthcare",
    "hospitality and services",
    "public service",
    "sales and marketing",
    "skilled trades",
    "student",
    "other",
    "prefer not to say",
]
IncomeFrequency = Literal["monthly", "fortnightly", "weekly", "irregular"]
IncomeStability = Literal["stable", "variable", "seasonal", "not applicable"]
HousingStatus = Literal[
    "family home",
    "renting",
    "homeowner with mortgage",
    "homeowner without mortgage",
    "other",
    "prefer not to say",
]
FinancialLiteracy = Literal["beginner", "intermediate", "advanced"]
AgeBand = Literal["18-20", "21-25", "26-30", "31-35", "Prefer not to say"]
GenderIdentity = Literal["Woman", "Man", "Non-binary", "Another identity", "Prefer not to say"]
RaceEthnicity = Literal[
    "Chinese", "Malay", "Indian", "Eurasian", "Other", "Prefer not to say"
]
NationalityResidency = Literal[
    "Singapore citizen",
    "Permanent resident",
    "Work or student pass holder",
    "Other",
    "Prefer not to say",
]
DisabilityStatus = Literal[
    "No disability disclosed", "Disability disclosed", "Prefer not to say"
]
MaritalStatus = Literal[
    "Single",
    "Married or partnered",
    "Separated or divorced",
    "Widowed",
    "Prefer not to say",
]
ResidentialRegion = Literal[
    "Central", "East", "North", "North-East", "West", "Outside Singapore", "Prefer not to say"
]


class ProfileUpsert(BaseModel):
    monthly_income: MoneyAmount | None = None
    risk_tolerance: str | None = Field(default=None, max_length=32)
    employment_status: EmploymentStatus | None = None
    occupation_category: OccupationCategory | None = None
    income_frequency: IncomeFrequency | None = None
    income_stability: IncomeStability | None = None
    household_size: int | None = Field(default=None, ge=1, le=30)
    dependants: int | None = Field(default=None, ge=0, le=20)
    housing_status: HousingStatus | None = None
    financial_literacy: FinancialLiteracy | None = None
    preferred_language: str | None = Field(default=None, max_length=32)
    accessibility_preferences: list[str] = Field(default_factory=list, max_length=20)
    preferences: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_household(self) -> "ProfileUpsert":
        if (
            self.household_size is not None
            and self.dependants is not None
            and self.dependants > self.household_size
        ):
            raise ValueError("Dependants cannot exceed household size")
        return self


class ProfileCreate(ProfileUpsert):
    user_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class ProfileResponse(ProfileUpsert):
    user_id: str


class ProfileSummary(BaseModel):
    user_id: str
    display_name: str
    monthly_income: MoneyAmount | None
    risk_tolerance: str | None


class DemographicUpsert(BaseModel):
    age_band: AgeBand | None = None
    gender_identity: GenderIdentity | None = None
    race_ethnicity: list[RaceEthnicity] = Field(default_factory=list, max_length=6)
    nationality_residency: NationalityResidency | None = None
    disability_status: DisabilityStatus | None = None
    marital_status: MaritalStatus | None = None
    residential_region: ResidentialRegion | None = None

    @model_validator(mode="after")
    def validate_race_ethnicity(self) -> "DemographicUpsert":
        if len(self.race_ethnicity) != len(set(self.race_ethnicity)):
            raise ValueError("Race or ethnicity selections must be unique")
        if "Prefer not to say" in self.race_ethnicity and len(self.race_ethnicity) > 1:
            raise ValueError("Prefer not to say cannot be combined with another selection")
        return self


class DemographicResponse(DemographicUpsert):
    user_id: str


class FairnessConsentUpdate(BaseModel):
    granted: bool


class FairnessConsentResponse(BaseModel):
    purpose: str
    consent_version: str
    granted: bool
    granted_at: datetime | None
    withdrawn_at: datetime | None


class FairnessProfileResponse(BaseModel):
    consent: FairnessConsentResponse
    demographics: DemographicResponse | None


class DataConsentUpdate(BaseModel):
    granted: bool


class DataConsentResponse(BaseModel):
    purpose: str
    consent_version: str
    granted: bool
    granted_at: datetime | None
    withdrawn_at: datetime | None
    feature_enabled: bool


class DataLifecycleResponse(BaseModel):
    policy_version: str
    effective_on: date
    export_schema_version: int
    retention: dict[str, int | str]
    durable_memory: DataConsentResponse


class UserDataExportResponse(BaseModel):
    schema_version: int
    policy_version: str
    exported_at: datetime
    user_id: str
    ownership: dict[str, bool]
    retention: dict[str, int | str]
    data: dict[str, Any]


class UserDataDeletionRequest(BaseModel):
    confirm_user_id: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=64)


class UserDataDeletionReceipt(BaseModel):
    request_id: UUID
    policy_version: str
    completed_at: datetime
    deleted_counts: dict[str, int]


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


class SpendingInsight(BaseModel):
    """Spending insight returned to frontend with explanations and suggestions."""
    insight_id: str
    insight_type: Literal["trend", "pattern", "anomaly", "opportunity"]
    title: str
    description: str
    category: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    data_refs: list[str]
    suggested_action: str | None = None
    severity: str | None = None
    explanation: str | None = None  # Why this matters
    educational_context: str | None = None  # Learning information


class BudgetAlertCategory(BaseModel):
    category: str
    spent: float
    limit_amount: float


class BudgetAlert(BaseModel):
    status: Literal["over", "approaching"]
    income_usage_percent: float | None
    budget_usage_percent: float | None
    over_income: bool
    over_budget: bool
    categories_over: list[BudgetAlertCategory]
    categories_at_limit: list[BudgetAlertCategory]
    amount_over_income: float
    amount_over_budget: float
    total_spent: float
    monthly_income: float
    total_budget_limit: float


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
    spending_insights: list[SpendingInsight] = Field(default_factory=list)
    spending_data_quality: str = "insufficient"
    spending_months_analyzed: int = 0
    budget_alert: BudgetAlert | None = None


class ChatSessionCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def normalize_title(self) -> "ChatSessionCreate":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Conversation title is required")
        return self


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def normalize_title(self) -> "ChatSessionUpdate":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Conversation title is required")
        return self


class AgentExplanationResponse(BaseModel):
    agent: AgentName
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    blocked: bool = False


class ChatExplanationResponse(BaseModel):
    trace_id: str
    response_language: Literal["English", "Chinese"] = "English"
    selected_agents: list[AgentName] = Field(default_factory=list)
    routing_rationale: list[str] = Field(default_factory=list)
    agent_results: list[AgentExplanationResponse] = Field(default_factory=list)
    blocked: bool = False
    prompt_set_version: str | None = None

    @field_validator("response_language", mode="before")
    @classmethod
    def normalize_language(cls, value: Any) -> str:
        return normalize_response_language(value)

    @model_validator(mode="after")
    @trace_method
    def sanitize_blocked_explanation(self) -> "ChatExplanationResponse":
        if self.blocked:
            self.routing_rationale = [
                blocked_agent_rationale(response_language=self.response_language)
            ]
            self.agent_results = [
                AgentExplanationResponse(
                    agent=item["agent"],
                    rationale=item["rationale"],
                    confidence=item["confidence"],
                    blocked=True,
                )
                for item in sanitize_blocked_agent_results(
                    self.agent_results, response_language=self.response_language
                )
            ]
        return self


class ChatMessageResponse(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    sources: list[SourceCitation] = Field(default_factory=list)
    explanation: ChatExplanationResponse | None = None
    created_at: datetime

    @model_validator(mode="after")
    @trace_method
    def sanitize_blocked_assistant_message(self) -> "ChatMessageResponse":
        if self.role == "assistant" and self.explanation and self.explanation.blocked:
            self.content = blocked_response_answer(
                response_language=self.explanation.response_language, answer=self.content
            )
            self.sources = []
        return self


class ChatSessionSummary(BaseModel):
    id: str
    user_id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class ChatSessionResponse(ChatSessionSummary):
    messages: list[ChatMessageResponse]
