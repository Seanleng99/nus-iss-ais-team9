from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AgentName(StrEnum):
    SPENDING = "spending"
    BUDGET = "budget"
    GOAL_STRATEGY = "goal_strategy"
    INVESTMENT_EDUCATION = "investment_education"
    RISK_COMPLIANCE = "risk_compliance"


class CapabilityName(StrEnum):
    TRANSACTION_CATEGORY_TOTALS = "transaction_category_totals"
    MONTHLY_BUDGET_BASELINE = "monthly_budget_baseline"
    MONTHLY_SAVINGS_CAPACITY = "monthly_savings_capacity"
    GOAL_PROJECTION = "goal_projection"
    EDUCATION_CONTEXT = "education_context"
    POLICY_CONTEXT = "policy_context"


class CapabilityProviderType(StrEnum):
    AGENT = "agent"
    TOOL = "tool"


class AgentTaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_FOR_DEPENDENCY = "waiting_for_dependency"
    COMPLETED = "completed"
    PARTIAL = "partial"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    BLOCKED_BY_DEPENDENCY = "blocked_by_dependency"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    historical_transactions: list[Transaction] = Field(default_factory=list)
    goals: list[FinancialGoal] = Field(default_factory=list)
    risk_tolerance: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    period_start: str | None = None


class ConversationMessage(StrictContractModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1500)


class CoachRequest(BaseModel):
    user_id: str
    session_id: str
    message: str = Field(min_length=1, max_length=5000)
    snapshot: UserFinancialSnapshot = Field(default_factory=UserFinancialSnapshot)
    requested_agents: list[AgentName] | None = None
    conversation_context: list[ConversationMessage] = Field(default_factory=list, max_length=8)

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


class CapabilityResult(StrictContractModel):
    capability: CapabilityName
    provider: str
    provider_task_id: str
    data: dict[str, Any]
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    input_fingerprint: str | None = None


class DependencyRequest(StrictContractModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    requester_task_id: str
    requester: AgentName
    capability: CapabilityName
    reason_code: str = Field(min_length=1, max_length=128)
    required_output_fields: list[str] = Field(default_factory=list, max_length=20)
    required: bool = True
    input_fingerprint: str | None = None


class DependencyResolution(StrictContractModel):
    request_id: str
    capability: CapabilityName
    requester_task_id: str
    provider_task_id: str | None = None
    resolution: Literal["reused", "scheduled", "resolved", "rejected"]
    reason_code: str | None = None
    input_fingerprint: str | None = None


class DependencyEdge(StrictContractModel):
    requester_task_id: str
    provider_task_id: str
    capability: CapabilityName


class AgentTask(StrictContractModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    agent: AgentName
    sanitized_message: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    context_features: dict[str, Any] = Field(default_factory=dict)
    status: AgentTaskStatus = AgentTaskStatus.READY
    attempt: int = Field(default=1, ge=1, le=10)
    requested_by: AgentName | None = None
    resolved_dependencies: dict[CapabilityName, CapabilityResult] = Field(default_factory=dict)
    dependency_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_role_scope(self):
        allowed_fields = {
            AgentName.SPENDING: {"recent_transactions"},
            AgentName.BUDGET: {"monthly_income", "recurring_expenses"},
            AgentName.GOAL_STRATEGY: {"goals"},
            AgentName.INVESTMENT_EDUCATION: {"risk_tolerance"},
        }
        allowed = allowed_fields.get(self.agent)
        if allowed is None:
            raise ValueError(f"{self.agent.value} is not a schedulable specialist")
        unexpected = set(self.input_data) - allowed
        if unexpected:
            raise ValueError(
                f"{self.agent.value} task contains fields outside its role scope: "
                f"{sorted(unexpected)}"
            )
        for capability, result in self.resolved_dependencies.items():
            if result.capability != capability:
                raise ValueError("Resolved dependency key does not match its capability result")
        return self


class CompletedInvocation(StrictContractModel):
    status: Literal["completed"] = "completed"
    result: AgentResult
    capabilities: list[CapabilityResult] = Field(default_factory=list)


class NeedsDependencyInvocation(StrictContractModel):
    status: Literal["needs_dependency"] = "needs_dependency"
    dependency_requests: list[DependencyRequest] = Field(min_length=1, max_length=4)


class NeedsInputInvocation(StrictContractModel):
    status: Literal["needs_input"] = "needs_input"
    reason_code: str = Field(min_length=1, max_length=128)
    questions: list[str] = Field(min_length=1, max_length=4)


class FailedInvocation(StrictContractModel):
    status: Literal["failed"] = "failed"
    error_code: str = Field(min_length=1, max_length=128)
    retryable: bool = False
    safe_message: str = Field(min_length=1, max_length=500)


AgentInvocationResult = Annotated[
    CompletedInvocation | NeedsDependencyInvocation | NeedsInputInvocation | FailedInvocation,
    Field(discriminator="status"),
]


class DependencyRequestDraft(StrictContractModel):
    capability: CapabilityName
    reason_code: str = Field(min_length=1, max_length=128)
    required_output_fields: list[str] = Field(default_factory=list, max_length=20)
    required: bool = True
    selection_guidance: str = Field(min_length=1, max_length=500)


class DependencyRequestSelection(StrictContractModel):
    capability: CapabilityName
    reason_code: str = Field(min_length=1, max_length=128)
    required_output_fields: list[str] = Field(default_factory=list, max_length=20)
    required: bool = True


class DependencyPlanningDecision(StrictContractModel):
    status: Literal["ready", "needs_dependency", "needs_input"]
    requests: list[DependencyRequestSelection] = Field(default_factory=list, max_length=4)
    questions: list[str] = Field(default_factory=list, max_length=4)
    reason_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_status_payload(self):
        if self.status == "ready" and (self.requests or self.questions):
            raise ValueError("ready dependency decisions cannot include requests or questions")
        if self.status == "needs_dependency" and not self.requests:
            raise ValueError("needs_dependency decisions require at least one request")
        if self.status == "needs_dependency" and self.questions:
            raise ValueError("dependency decisions cannot also request user input")
        if self.status == "needs_input" and not self.questions:
            raise ValueError("needs_input decisions require at least one question")
        if self.status == "needs_input" and self.requests:
            raise ValueError("user-input decisions cannot also request dependencies")
        return self


class CapabilityDefinition(StrictContractModel):
    capability: CapabilityName
    provider: str
    provider_type: CapabilityProviderType
    allowed_requesters: set[AgentName]
    required_inputs: list[str] = Field(default_factory=list)
    maximum_calls_per_run: int = Field(default=1, ge=1, le=10)
    cacheable_within_run: bool = True


class AuditEvent(StrictContractModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str
    event_type: str
    actor: str
    occurred_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    task_id: str | None = None
    parent_task_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SourceCitation(BaseModel):
    source_id: str
    title: str
    issuing_organization: str
    canonical_url: str
    published_at: str
    document_version: str
    checksum: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    corpus_version: str
    review_due_at: str
    document_filename: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$",
    )
    content_kind: Literal["source_document", "project_summary"] | None = None


class RouterDecision(BaseModel):
    selected_agents: list[AgentName] = Field(min_length=1, max_length=4)
    rationale: list[str] = Field(min_length=1)
    education_topics: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("selected_agents")
    @classmethod
    def validate_selected_agents(cls, value: list[AgentName]) -> list[AgentName]:
        if AgentName.RISK_COMPLIANCE in value:
            raise ValueError("risk_compliance is a mandatory post-routing agent")
        return list(dict.fromkeys(value))


class AgentNarrative(BaseModel):
    summary: str = Field(min_length=1, max_length=3000)
    rationale: list[str] = Field(min_length=1, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)


class GroundedEducationNarrative(AgentNarrative):
    source_ids: list[str] = Field(min_length=1, max_length=3)
    uncertainties: list[str] = Field(default_factory=list, max_length=4)


class GeneralEducationSection(BaseModel):
    topic: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1500)


class HybridEducationNarrative(GroundedEducationNarrative):
    summary: str = Field(default="", max_length=3000)
    source_ids: list[str] = Field(default_factory=list, max_length=9)
    general_knowledge: list[GeneralEducationSection] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def bound_combined_answer(self) -> "HybridEducationNarrative":
        if len(self.summary) + sum(len(section.text) for section in self.general_knowledge) > 5000:
            raise ValueError("Combined education content must fit within 5000 characters.")
        return self


class SynthesisDecision(BaseModel):
    answer: str = Field(min_length=1, max_length=6000)


class ComplianceDecision(BaseModel):
    blocked: bool
    summary: str = Field(min_length=1, max_length=2000)
    rationale: list[str] = Field(min_length=1, max_length=8)
    policy_notes: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)


class EducationComplianceDecision(ComplianceDecision):
    request_allowed: bool
    complete: bool
    missing_points: list[str] = Field(max_length=6)
    repairable: bool = False
    financial_language_safe: bool = Field(default=False, strict=True)

    @field_validator("missing_points")
    @classmethod
    def bound_missing_points(cls, value: list[str]) -> list[str]:
        if any(not point.strip() or len(point) > 200 for point in value):
            raise ValueError("Missing points must be brief, nonempty requirements.")
        return value


# Spending Analysis Models


class Trend(BaseModel):
    """Category trend detection result."""
    category: str
    current_amount: float
    previous_amount: float
    change_percent: float
    change_absolute: float
    significance: Literal["low", "moderate", "high"]
    direction: Literal["increased", "decreased", "stable"]


class TemporalPattern(BaseModel):
    """Temporal spending pattern."""
    pattern_type: Literal["weekday_weekend", "day_of_week", "monthly_cycle"]
    description: str
    metric: str
    value: float
    baseline: float
    variance_percent: float
    confidence: float


class Anomaly(BaseModel):
    """Detected spending anomaly."""
    transaction_id: str | None
    category: str
    amount: float
    expected_amount: float
    deviation_percent: float
    z_score: float | None
    detection_method: Literal["z_score", "iqr", "rule_based"]
    occurred_on: str
    severity: Literal["low", "medium", "high"]


class SpendingInsight(BaseModel):
    """Final spending insight presented to user."""
    insight_id: str
    insight_type: Literal["trend", "pattern", "anomaly", "opportunity"]
    title: str
    description: str
    category: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    data_refs: list[str]
    suggested_action: str | None
    severity: str | None


class SpendingAnalysisResult(BaseModel):
    """Complete spending analysis result."""
    summary: str
    insights: list[SpendingInsight]
    category_trends: list[Trend]
    temporal_patterns: list[TemporalPattern]
    anomalies: list[Anomaly]
    data_quality: Literal["insufficient", "limited", "good", "excellent"]
    months_analyzed: int


class CoachResponse(BaseModel):
    session_id: str
    selected_agents: list[AgentName]
    answer: str
    agent_results: list[AgentResult]
    disclaimers: list[str]
    sources: list[SourceCitation] = Field(default_factory=list)
    audit: dict[str, Any]
    blocked: bool = False
