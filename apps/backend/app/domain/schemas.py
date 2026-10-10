import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from coach_i18n import SupportedLocale, normalize_locale, translate
from coach_trace.review import review_metadata
from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.telemetry import log_event, trace_method
from app.domain.currency import ApplicationCurrency
from app.domain.recurrence import LedgerRecurrence


class AgentName(StrEnum):
    SPENDING = "spending"
    BUDGET = "budget"
    GOAL_STRATEGY = "goal_strategy"
    INVESTMENT_EDUCATION = "investment_education"
    RISK_COMPLIANCE = "risk_compliance"


class MoneyAmount(BaseModel):
    currency: str = Field(default="SGD", pattern=r"^[A-Z]{3}$")
    amount: float = Field(ge=0)


class ApplicationMoneyAmount(MoneyAmount):
    """New financial inputs are always SGD; foreign amounts are rejected."""

    currency: ApplicationCurrency = "SGD"


class Transaction(BaseModel):
    description: str
    category: str
    amount: MoneyAmount
    occurred_on: str
    recurring: bool = False
    recurrence: LedgerRecurrence | None = None
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
    period_start: str | None = None
    goals: list[FinancialGoal] = Field(default_factory=list)
    risk_tolerance: str | None = None
    preferences: dict[str, Any] = Field(default_factory=dict)


class CoachRequest(BaseModel):
    user_id: str
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=5000)
    response_locale: SupportedLocale | None = None
    budget_period_start: date | None = None
    snapshot: UserFinancialSnapshot = Field(default_factory=UserFinancialSnapshot)
    requested_agents: list[AgentName] | None = None

    @field_validator("budget_period_start")
    @classmethod
    def validate_budget_period(cls, value):
        log_event("VV entering ", "app.domain.schemas.CoachRequest", "validate_budget_period")
        if value is not None and value.day != 1:
            raise ValueError("Budget period must be the first day of a month")
        return value

    @field_validator("response_locale", mode="before")
    @classmethod
    def validate_response_locale(cls, value):
        log_event("VV entering ", "app.domain.schemas.CoachRequest", "validate_response_locale")
        if value is None:
            return None
        locale = normalize_locale(value)
        if locale is None:
            raise ValueError("Supported response locales are en and zh-Hans")
        return locale

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        log_event("VV entering ", "app.domain.schemas.CoachRequest", "strip_message")
        return value.strip()


class InternalCoachRequest(CoachRequest):
    # Only the backend constructs this; the public request has no history field.
    conversation_context: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    message_position: int | None = Field(default=None, ge=1)
    pending_goal: dict[str, Any] | None = None
    pending_budget: dict[str, Any] | None = None
    pending_transaction: dict[str, Any] | None = None
    budget_context: dict[str, Any] = Field(default_factory=dict)
    saved_budget_capacity: dict[str, Any] = Field(default_factory=dict)
    session_context: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent: AgentName
    summary: str
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    data: dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    policy_notes: list[str] = Field(default_factory=list)


BLOCKED_RESPONSE_ANSWER = translate('safety.withheld_answer', 'en')
BLOCKED_AGENT_SUMMARY = translate('safety.withheld_summary', 'en')
BLOCKED_AGENT_RATIONALE = translate('safety.withheld_rationale', 'en')
BLOCKED_ROUTING_RATIONALE = translate('safety.withheld_summary', 'en')
BLOCKED_RESPONSE_ANSWER_ZH = translate('safety.withheld_answer', 'zh-Hans')
BROKERAGE_RESPONSE_ANSWER = translate('safety.brokerage_refusal', 'en')
BROKERAGE_RESPONSE_ANSWER_ZH = translate('safety.brokerage_refusal', 'zh-Hans')
SAFE_REFUSAL_KEYS = (
    "safety.unverified_answer", "safety.action_refusal", "safety.brokerage_refusal",
    "safety.personal_investment_refusal", "safety.product_return_refusal",
    "safety.unverified_narrow_question",
)
SAFE_REFUSAL_TEMPLATES = tuple(
    (translate(key, "en"), translate(key, "zh-Hans")) for key in SAFE_REFUSAL_KEYS
)
BLOCKED_AGENT_SUMMARY_ZH = translate('safety.withheld_summary', 'zh-Hans')
BLOCKED_AGENT_RATIONALE_ZH = translate('safety.withheld_rationale', 'zh-Hans')
BLOCKED_ROUTING_RATIONALE_ZH = translate('safety.withheld_summary', 'zh-Hans')
BLOCKED_POLICY_NOTE = "response_withheld"
BLOCKED_EDUCATIONAL_DISCLAIMER = translate("safety.educational_disclaimer", "en")
SAFE_REGULATED_ADVICE_CODES = frozenset(
    {
        "regulated_advice:guaranteed return",
        "regulated_advice:which stock should i buy",
        "regulated_advice:tell me exactly what to invest in",
        "regulated_advice:buy or sell",
    }
)
SAFE_PERSONALIZED_ADVICE_CODES = frozenset(
    {
        "regulated_advice:personalized_allocation",
        "regulated_advice:personalized_transaction",
        "regulated_advice:personalized_product",
        "regulated_advice:personalized_product_selection",
        "regulated_advice:personalized_transaction_request",
        "regulated_advice:personalized_investment_instruction",
    }
)
SAFE_PII_CODES = frozenset({"email", "phone", "nric_like"})
SAFE_PROMPT_INJECTION_CODE = re.compile(r"^prompt_injection:(?:[0-9]|1[01])$")
SAFE_POLICY_EVIDENCE_CODE = "policy_evidence:insufficient"


def normalize_response_language(value: Any) -> Literal["English", "Chinese"]:
    # Historical audit values are untrusted; preserve the strict read boundary.
    # Request aliases are normalized separately by the request contract.
    log_event("VV entering ", "app.domain.schemas", "normalize_response_language")
    return "Chinese" if value == "Chinese" else "English"


def blocked_response_answer(
    *, response_language: str = "English", answer: str | None = None
) -> str:
    # Only exact, reviewed templates may survive a blocked response. Never pass through model text.
    log_event("VV entering ", "app.domain.schemas", "blocked_response_answer")
    response_language = normalize_response_language(response_language)
    for key in SAFE_REFUSAL_KEYS:
        if answer in (translate(key, "en"), translate(key, "zh-Hans")):
            return translate(key, response_language)
    return translate("safety.withheld_answer", response_language)


def blocked_agent_rationale(*, response_language: str = "English") -> str:
    log_event("VV entering ", "app.domain.schemas", "blocked_agent_rationale")
    response_language = normalize_response_language(response_language)
    return translate("safety.withheld_rationale", response_language)


def _safe_policy_notes(notes: list[str]) -> list[str]:
    log_event("VV entering ", "app.domain.schemas", "_safe_policy_notes")
    safe_notes = [
        note
        for note in notes
        if note in SAFE_REGULATED_ADVICE_CODES
        or note in SAFE_PERSONALIZED_ADVICE_CODES
        or note in SAFE_PII_CODES
        or note == SAFE_POLICY_EVIDENCE_CODE
        or SAFE_PROMPT_INJECTION_CODE.fullmatch(note)
    ]
    if BLOCKED_POLICY_NOTE not in safe_notes:
        safe_notes.append(BLOCKED_POLICY_NOTE)
    return safe_notes


def blocked_agent_result(
    agent: AgentName | str,
    policy_notes: list[str] | None = None,
    *,
    response_language: str = "English",
) -> dict[str, Any]:
    log_event("VV entering ", "app.domain.schemas", "blocked_agent_result")
    response_language = normalize_response_language(response_language)
    return {
        "agent": agent.value if isinstance(agent, AgentName) else agent,
        "summary": translate("safety.withheld_summary", response_language),
        "rationale": [blocked_agent_rationale(response_language=response_language)],
        "confidence": 1.0,
        "data": {},
        "blocked": True,
        "policy_notes": _safe_policy_notes(policy_notes or []),
    }


def sanitize_blocked_agent_results(
    agent_results: list[Any], *, response_language: str = "English"
) -> list[dict[str, Any]]:
    log_event("VV entering ", "app.domain.schemas", "sanitize_blocked_agent_results")
    sanitized: list[dict[str, Any]] = []
    for item in agent_results:
        agent = (
            getattr(item, "agent", None)
            if isinstance(item, BaseModel)
            else item.get("agent", "unknown")
        )
        if agent is None:
            agent = "unknown"
        notes = (
            getattr(item, "policy_notes", [])
            if isinstance(item, BaseModel)
            else item.get("policy_notes", [])
        )
        sanitized.append(
            blocked_agent_result(agent, notes, response_language=response_language)
        )
        if str(agent) == AgentName.RISK_COMPLIANCE.value:
            data = getattr(item, "data", {}) if isinstance(item, BaseModel) else item.get("data", {})
            sanitized[-1]["data"] = review_metadata(data)
    return sanitized


def sanitize_blocked_audit(audit: dict[str, Any]) -> dict[str, Any]:
    log_event("VV entering ", "app.domain.schemas", "sanitize_blocked_audit")
    sanitized = dict(audit)
    response_language = normalize_response_language(audit.get("response_language"))
    sanitized["response_language"] = response_language
    sanitized["routing_rationale"] = [
        translate("safety.withheld_summary", response_language)
    ]
    return sanitized


class SourceCitation(BaseModel):
    source_id: str
    title: str
    issuing_organization: str
    canonical_url: str
    published_at: str
    document_version: str | None = None
    checksum: str | None = None
    corpus_version: str | None = None
    review_due_at: str | None = None
    document_filename: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$"
    )
    content_kind: Literal["source_document", "project_summary"] | None = None


class CoachResponse(BaseModel):
    session_id: str
    selected_agents: list[AgentName]
    answer: str
    agent_results: list[AgentResult]
    disclaimers: list[str]
    sources: list[SourceCitation] = Field(default_factory=list)
    audit: dict[str, Any]
    blocked: bool = False

    @model_validator(mode="after")
    @trace_method
    def sanitize_blocked_response(self) -> "CoachResponse":
        log_event("VV entering ", "app.domain.schemas.CoachResponse", "sanitize_blocked_response")
        if self.blocked:
            self.audit = sanitize_blocked_audit(self.audit)
            response_language = self.audit["response_language"]
            self.answer = blocked_response_answer(
                response_language=response_language, answer=self.answer
            )
            self.sources = []
            self.agent_results = [
                AgentResult.model_validate(item)
                for item in sanitize_blocked_agent_results(
                    self.agent_results, response_language=response_language
                )
            ]
            self.disclaimers = [
                translate("safety.educational_disclaimer", response_language),
                blocked_agent_rationale(response_language=response_language),
            ]
        return self


TraceStatus = Literal["running", "completed", "blocked", "failed", "timed_out", "abandoned"]


class OrchestrationRunSummary(BaseModel):
    trace_id: str
    session_id: str
    conversation_title: str
    status: TraceStatus
    selected_agents: list[AgentName]
    created_at: datetime
    finished_at: datetime | None = None
    error_code: str | None = None


class OrchestrationRunPage(BaseModel):
    items: list[OrchestrationRunSummary]
    next_offset: int | None = None


class OrchestrationTraceResponse(BaseModel):
    trace_id: str
    session_id: str
    assistant_message_id: str | None
    status: TraceStatus = "completed"
    correlation_id: str | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    selected_agents: list[AgentName]
    agent_results: list[AgentResult]
    audit: dict[str, Any]
    blocked: bool
    model_provider: str | None = None
    model_id: str | None = None
    prompt_set_version: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def sanitize_blocked_trace(self) -> "OrchestrationTraceResponse":
        log_event("VV entering ", "app.domain.schemas.OrchestrationTraceResponse", "sanitize_blocked_trace")
        if self.blocked:
            self.audit = sanitize_blocked_audit(self.audit)
            self.agent_results = [
                AgentResult.model_validate(item)
                for item in sanitize_blocked_agent_results(
                    self.agent_results, response_language=self.audit["response_language"]
                )
            ]
        return self
