import re
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from coach_i18n import SupportedLocale, normalize_locale
from coach_math.budget_scope import BudgetScope
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator


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


class TransactionRecurrence(BaseModel):
    frequency: Literal["once", "weekly", "fortnightly", "monthly", "yearly"]
    interval: int = Field(default=1, ge=1, le=120)
    first_on: date
    next_due_on: date
    last_on: date | None = None
    month_end: bool = False


class Transaction(BaseModel):
    description: str
    category: str
    amount: MoneyAmount
    occurred_on: str
    recurrence: TransactionRecurrence | None = None
    obligation_id: str | None = None


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
    transaction_context: dict[str, Any] = Field(default_factory=dict)
    goals: list[FinancialGoal] = Field(default_factory=list)
    risk_tolerance: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)
    period_start: str | None = None


class ConversationMessage(StrictContractModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1500)
    answer_status: Literal["available", "withheld", "unavailable", "needs_input"] = "available"


SessionField = Literal[
    "monthly_income", "monthly_expenses", "goal_target_amount", "goal_current_amount",
    "goal_name", "goal_target_months", "budget_period_start",
]


class SessionFact(StrictContractModel):
    value: str = Field(min_length=1, max_length=120)
    source_position: int = Field(ge=1)
    status: Literal["user_reported"] = "user_reported"
    supersedes_position: int | None = Field(default=None, ge=1)


class ConversationNote(StrictContractModel):
    source_position: int = Field(ge=1)
    assistant_position: int = Field(ge=2)
    kind: Literal["preference", "objective", "discussion"]
    topics: list[Literal["spending", "budget", "goal_strategy", "investment_education"]] = Field(max_length=4)
    user_excerpt: str = Field(min_length=1, max_length=240)
    assistant_excerpt: str = Field(max_length=160)


class OlderConversationSummary(StrictContractModel):
    through_position: int = Field(ge=0)
    notes: list[ConversationNote] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_sources(self):
        previous = 0
        for note in self.notes:
            if not previous < note.source_position < note.assistant_position <= self.through_position:
                raise ValueError("Summary notes must reference ordered older exchanges")
            if note.assistant_position != note.source_position + 1:
                raise ValueError("Summary excerpts must reference a single exchange")
            previous = note.assistant_position
        return self


class AttributedObservation(StrictContractModel):
    """An interpretation of an exact user excerpt, never authority for a write."""

    kind: Literal["fact", "preference", "objective", "discussion"]
    field: SessionField | None = None
    value: str | None = Field(default=None, min_length=1, max_length=120)
    source_quote: str = Field(min_length=1, max_length=240)
    source_position: int = Field(ge=1)
    attribution: Literal["self", "general", "other", "hypothetical", "quoted"]
    cadence: Literal["monthly", "once", "unknown"] = "unknown"
    topics: list[Literal["spending", "budget", "goal_strategy", "investment_education"]] = Field(default_factory=list, max_length=4)


class ConversationReferent(StrictContractModel):
    subject: str = Field(min_length=1, max_length=160)
    agent: Literal["spending", "budget", "goal_strategy", "investment_education"]
    education_topics: list[str] = Field(default_factory=list, max_length=12)
    source_quote: str = Field(min_length=1, max_length=240)
    source_position: int = Field(ge=1)
    option_index: int | None = Field(default=None, ge=1, le=12)


class SessionContext(StrictContractModel):
    version: Literal[1] = 1
    facts: dict[SessionField, SessionFact] = Field(default_factory=dict, max_length=7)
    active_topic: Literal["spending", "budget", "goal_strategy", "investment_education"] | None = None
    pending_fields: list[SessionField] = Field(default_factory=list, max_length=7)
    last_stated_fields: list[SessionField] = Field(default_factory=list, max_length=7)
    uncertain_fields: list[SessionField] = Field(default_factory=list, max_length=7)
    pending_action: Literal["budget_status"] | None = None
    older_summary: OlderConversationSummary | None = None
    observations: list[AttributedObservation] = Field(default_factory=list, max_length=12)
    referents: list[ConversationReferent] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_fact_values(self):
        for field, fact in self.facts.items():
            if field in {"monthly_income", "monthly_expenses", "goal_target_amount", "goal_current_amount"}:
                if not re.fullmatch(r"\d{1,12}(?:\.\d{1,2})?", fact.value) or Decimal(fact.value) > Decimal("999999999999.99"):
                    raise ValueError("Session monetary values must be bounded SGD decimal strings")
            elif field == "goal_target_months":
                if not fact.value.isdecimal() or not 1 <= int(fact.value) <= 600:
                    raise ValueError("Session duration must be between 1 and 600 months")
            elif field == "budget_period_start" and date.fromisoformat(fact.value).day != 1:
                raise ValueError("Session budget period must start on the first day")
            if fact.supersedes_position and fact.supersedes_position >= fact.source_position:
                raise ValueError("A correction must follow the statement it supersedes")
        return self


class CoachRequest(BaseModel):
    user_id: str
    session_id: str
    message: str = Field(min_length=1, max_length=5000)
    message_position: int | None = Field(default=None, ge=1)
    response_locale: SupportedLocale | None = None
    snapshot: UserFinancialSnapshot = Field(default_factory=UserFinancialSnapshot)
    requested_agents: list[AgentName] | None = None
    conversation_context: list[ConversationMessage] = Field(default_factory=list, max_length=8)
    pending_goal: dict[str, Any] | None = None
    pending_budget: dict[str, Any] | None = None
    pending_transaction: dict[str, Any] | None = None
    budget_context: dict[str, Any] = Field(default_factory=dict)
    saved_budget_capacity: dict[str, Any] = Field(default_factory=dict)
    session_context: SessionContext = Field(default_factory=SessionContext)

    @field_validator("response_locale", mode="before")
    @classmethod
    def validate_response_locale(cls, value):
        if value is None:
            return None
        locale = normalize_locale(value)
        if locale is None:
            raise ValueError("Supported response locales are en and zh-Hans")
        return locale

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        return value.strip()


class AgentResult(BaseModel):
    _financial_grounding_snapshot: Any = PrivateAttr(default=None)
    # Server-created grounding authority never crosses a JSON/API boundary.
    _education_grounding_snapshot: Any = PrivateAttr(default=None)
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
    _financial_grounding_snapshot: Any = PrivateAttr(default=None)
    _education_grounding_snapshot: Any = PrivateAttr(default=None)
    _budget_requires_income: bool | None = PrivateAttr(default=None)
    _goal_requires_capacity: bool | None = PrivateAttr(default=None)
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
            AgentName.SPENDING: {"recent_transactions", "historical_transactions", "period_start", "transaction_context"},
            AgentName.BUDGET: {"monthly_income", "recurring_expenses", "period_start", "planning_context", "saved_budget_capacity"},
            AgentName.GOAL_STRATEGY: {"goals", "emergency_fund"},
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
    missing_fields: list[SessionField] = Field(default_factory=list, max_length=7)


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
    schema_version: Literal[1] = 1
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


class FollowUpResolution(StrictContractModel):
    status: Literal["standalone", "resolved", "ambiguous"] = "standalone"
    agent: AgentName | None = None
    subject: str | None = Field(default=None, max_length=240)
    education_topics: list[str] = Field(default_factory=list, max_length=12)
    source_kind: Literal["recent_dialogue", "older_summary", "session_fact", "saved_goal", "active_topic", "explicit_agent", "attributed_referent"] | None = None
    source_index: int | None = Field(default=None, ge=0, le=7)
    source_position: int | None = Field(default=None, ge=1)
    question: str | None = Field(default=None, max_length=200)
    reason_code: str = Field(default="NEW_QUESTION", max_length=128)


class TaskAssignment(StrictContractModel):
    """Model-selected work, attributed to this turn; never financial evidence."""

    agent: AgentName
    question: str = Field(min_length=1, max_length=5000)
    source_quotes: list[str] = Field(min_length=1, max_length=4)
    requires_spending: bool | None = None
    requires_income: bool | None = None
    requires_capacity: bool | None = None
    education_topics: list[str] = Field(default_factory=list, max_length=12)


class RouterDecision(BaseModel):
    task_assignments: list[TaskAssignment] = Field(default_factory=list, max_length=4)
    spending_scope: BudgetScope | None = None
    spending_scope_unclear: bool = False
    spending_analysis_period: date | None = None
    budget_scope: BudgetScope | None = None
    budget_scope_unclear: bool = False
    follow_up_source_index: int | None = Field(default=None, ge=0, le=7)
    follow_up_subject_position: int | None = Field(default=None, ge=1)
    follow_up_option_index: int | None = Field(default=None, ge=1, le=12)
    session_observations: list[AttributedObservation] = Field(default_factory=list, max_length=12)
    referents: list[ConversationReferent] = Field(default_factory=list, max_length=12)
    missing_fields: list[SessionField] = Field(default_factory=list, max_length=7)
    education_search_terms: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=12)
    budget_status_query: bool = False
    budget_capacity_query: bool = False
    budget_status_period_start: date | None = None
    memory_question: bool = False
    memory_fields: list[SessionField] = Field(default_factory=list, max_length=7)
    selected_agents: list[AgentName] = Field(min_length=1, max_length=4)
    rationale: list[str] = Field(min_length=1)
    education_topics: list[str] = Field(default_factory=list, max_length=12)
    goal_capture: bool = False
    budget_capture: bool = False
    budget_planning: bool = False
    spending_capture: bool = False

    @field_validator("selected_agents")
    @classmethod
    def validate_selected_agents(cls, value: list[AgentName]) -> list[AgentName]:
        if AgentName.RISK_COMPLIANCE in value:
            raise ValueError("risk_compliance is a mandatory post-routing agent")
        return list(dict.fromkeys(value))

    @field_validator("budget_status_period_start", "spending_analysis_period")
    @classmethod
    def validate_status_period(cls, value):
        if value is not None and value.day != 1:
            raise ValueError("Budget status period must start on the first day")
        return value


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


class EducationOption(BaseModel):
    topic: str = Field(min_length=1, max_length=100)
    sourced_text: str = Field(default="", max_length=1500)
    source_ids: list[str] = Field(default_factory=list, max_length=9)
    model_text: str = Field(default="", max_length=1500)


class HybridEducationNarrative(GroundedEducationNarrative):
    summary: str = Field(default="", max_length=3000)
    source_ids: list[str] = Field(default_factory=list, max_length=9)
    lead_section: Literal["sourced", "model"] = "sourced"
    general_knowledge: list[GeneralEducationSection] = Field(default_factory=list, max_length=12)
    ordered_options: list[EducationOption] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def bound_combined_answer(self) -> "HybridEducationNarrative":
        if (
            len(self.summary) + sum(len(section.text) for section in self.general_knowledge)
            + sum(len(option.sourced_text) + len(option.model_text) for option in self.ordered_options)
            > 5000
        ):
            raise ValueError("Combined education content must fit within 5000 characters.")
        return self


class SynthesisDecision(BaseModel):
    answer: str = Field(min_length=1, max_length=6000)
    referents: list[ConversationReferent] = Field(default_factory=list, max_length=12)


ComplianceCategory = Literal[
    "prohibited_request", "personal_advice", "return_guarantee", "privacy",
    "injection", "citation_attribution", "factual_qualification", "unverifiable_claim",
]


class ComplianceDecision(BaseModel):
    blocked: bool
    summary: str = Field(min_length=1, max_length=2000)
    rationale: list[str] = Field(min_length=1, max_length=8)
    policy_notes: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)
    block_categories: list[ComplianceCategory] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def explain_verdict(self):
        if self.blocked and (not self.block_categories or not any(note.strip() for note in self.policy_notes)):
            raise ValueError("A blocking verdict requires block_categories and a brief policy note")
        if not self.blocked and not isinstance(self, ScopedEducationComplianceDecision) and self.block_categories:
            raise ValueError("An allowed verdict must have empty block_categories")
        return self


class EducationReviewIssue(StrictContractModel):
    section_id: str = Field(min_length=1, max_length=80)
    requirement: str = Field(min_length=1, max_length=200)
    category: ComplianceCategory | None = None
    action: Literal["qualify", "ground_claim", "remove_claim", "complete"] = "qualify"
    evidence_refs: list[str] = Field(default_factory=list, max_length=6)
    claim_start: int | None = Field(default=None, ge=0, strict=True)
    claim_end: int | None = Field(default=None, ge=1, strict=True)

    @field_validator("requirement")
    @classmethod
    def nonempty_requirement(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Correction requirements must be nonempty")
        return value


class ScopedEducationComplianceDecision(ComplianceDecision):
    """Tie Education and financial defects to server-owned review sections."""

    request_allowed: bool
    complete: bool
    missing_points: list[str] = Field(max_length=6)
    financial_language_safe: bool = Field(default=False, strict=True)
    blocking_issues: list[EducationReviewIssue] = Field(default_factory=list, max_length=6)
    _repairable: bool = PrivateAttr(default=False)

    @property
    def repairable(self) -> bool:
        return self._repairable

    @model_validator(mode="after")
    def validate_scoped_verdict(self):
        veto = self.blocked or not self.request_allowed
        if veto and (not self.block_categories or not self.policy_notes or not self.blocking_issues):
            raise ValueError("A blocking verdict requires categories, a policy note and section-specific requirements")
        if not veto and (self.block_categories or (self.complete and self.blocking_issues)):
            raise ValueError("An allowed complete verdict cannot contain blocking categories or issues")
        if not self.request_allowed and "prohibited_request" not in self.block_categories:
            raise ValueError("A prohibited request requires the prohibited_request category")
        if self.complete and self.missing_points:
            raise ValueError("Complete answers have no missing_points; safety corrections belong in blocking_issues")
        if not self.complete and (
            not self.missing_points or not self.blocking_issues
            or not set(self.missing_points) <= {issue.requirement for issue in self.blocking_issues}
        ):
            raise ValueError("Incomplete answers require missing_points with matching section-specific requirements")
        if any(not point.strip() or len(point) > 200 for point in self.missing_points):
            raise ValueError("Missing points must be brief, nonempty requirements")
        return self


# Spending Analysis Models


class Trend(BaseModel):
    """Category trend detection result."""
    category: str
    current_amount: float
    previous_amount: float
    change_percent: float | None
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
