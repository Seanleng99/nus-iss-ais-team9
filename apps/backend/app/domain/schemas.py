import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.telemetry import trace_method


class AgentName(StrEnum):
    SPENDING = "spending"
    BUDGET = "budget"
    GOAL_STRATEGY = "goal_strategy"
    INVESTMENT_EDUCATION = "investment_education"
    RISK_COMPLIANCE = "risk_compliance"


class MoneyAmount(BaseModel):
    currency: str = Field(default="SGD", pattern=r"^[A-Z]{3}$")
    amount: float = Field(ge=0)


class Transaction(BaseModel):
    description: str
    category: str
    amount: MoneyAmount
    occurred_on: str
    recurring: bool = False


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
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=5000)
    budget_period_start: date | None = None
    snapshot: UserFinancialSnapshot = Field(default_factory=UserFinancialSnapshot)
    requested_agents: list[AgentName] | None = None

    @field_validator("budget_period_start")
    @classmethod
    def validate_budget_period(cls, value):
        if value is not None and value.day != 1:
            raise ValueError("Budget period must be the first day of a month")
        return value

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        return value.strip()


class InternalCoachRequest(CoachRequest):
    # Only the backend constructs this; the public request has no history field.
    conversation_context: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    pending_goal: dict[str, Any] | None = None
    pending_budget: dict[str, Any] | None = None
    budget_context: dict[str, Any] = Field(default_factory=dict)
    saved_budget_capacity: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent: AgentName
    summary: str
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    data: dict[str, Any] = Field(default_factory=dict)
    blocked: bool = False
    policy_notes: list[str] = Field(default_factory=list)


BLOCKED_RESPONSE_ANSWER = (
    "For your safety, this response has been withheld because it could not be safely verified."
)
BLOCKED_AGENT_SUMMARY = "Response withheld by safety controls."
BLOCKED_AGENT_RATIONALE = "The safety review blocked this response."
BLOCKED_ROUTING_RATIONALE = "Response withheld by safety controls."
BLOCKED_RESPONSE_ANSWER_ZH = "为保障您的安全，此回复因无法通过安全验证而被隐藏。"
BROKERAGE_RESPONSE_ANSWER = (
    "I can't log in to your brokerage account, handle your login details, or buy investments for you. "
    "I can explain how ETFs work, their fees and risks, and factors to consider when comparing them."
)
BROKERAGE_RESPONSE_ANSWER_ZH = (
    "我不能登录你的券商账户、接收登录凭证或代你买入投资产品。"
    "我可以解释 ETF 的运作方式、费用、风险，以及比较 ETF 时可以了解的因素。"
)
SAFE_REFUSAL_TEMPLATES = (
    (
        ("I couldn't verify this answer well enough to share it. "
         "You can ask me to explain a financial concept or review your recorded spending and savings goals."),
        ("我还不能充分核实这次回答，所以暂时无法提供。"
         "你可以让我解释一个金融概念，或查看你已记录的支出和储蓄目标。"),
    ),
    (
        ("I can't help with that action. I can explain general investment concepts, "
         "risks, and ways to check information through official sources."),
        ("我不能协助执行这项操作。我可以解释一般投资概念、风险，"
         "以及通过官方来源核实信息的方法。"),
    ),
    (BROKERAGE_RESPONSE_ANSWER, BROKERAGE_RESPONSE_ANSWER_ZH),
    (
        ("I can't choose investments or give personal buy, sell or allocation instructions. "
        "I can explain investment types, uncertainty and loss risk, fees, and general comparison factors."),
        ("我不能替你选择投资产品，或提供个人买卖和配置指示。"
        "我可以解释投资类别、回报的不确定性与亏损风险、费用及一般比较因素。"),
    ),
    (
        ("I cannot recommend an investment product or promise a return. "
        "I can explain return claims, risks, fees and ways to check providers "
        "through official sources, so you can understand and compare the information."),
        ("我不能推荐投资产品或承诺回报。可以解释收益声明、风险、费用，"
        "以及通过官方来源核实提供者的方法，供你了解和比较。"),
    ),
    (
        ("I couldn't verify this answer well enough to share it. "
        "Please try a narrower investment question, such as a definition or a comparison."),
        ("我还不能充分核实这次回答，所以暂时无法提供。"
        "你可以把问题缩小到一个投资概念的定义或比较，我会再尝试说明。"),
    ),
)
BLOCKED_AGENT_SUMMARY_ZH = "此回复已被安全措施拦截。"
BLOCKED_AGENT_RATIONALE_ZH = "安全审查已拦截此回复。"
BLOCKED_ROUTING_RATIONALE_ZH = "此回复已被安全措施拦截。"
BLOCKED_POLICY_NOTE = "response_withheld"
BLOCKED_EDUCATIONAL_DISCLAIMER = (
    "This is general financial education, not regulated financial advice. "
    "Consider consulting a licensed financial adviser for personal investment decisions."
)
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
    return "Chinese" if value == "Chinese" else "English"


def blocked_response_answer(
    *, response_language: str = "English", answer: str | None = None
) -> str:
    # Only exact, reviewed templates may survive a blocked response. Never pass through model text.
    for english, chinese in SAFE_REFUSAL_TEMPLATES:
        if answer in (english, chinese):
            return chinese if response_language == "Chinese" else english
    return (
        BLOCKED_RESPONSE_ANSWER_ZH
        if response_language == "Chinese"
        else BLOCKED_RESPONSE_ANSWER
    )


def blocked_agent_rationale(*, response_language: str = "English") -> str:
    return (
        BLOCKED_AGENT_RATIONALE_ZH
        if response_language == "Chinese"
        else BLOCKED_AGENT_RATIONALE
    )


def _safe_policy_notes(notes: list[str]) -> list[str]:
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
    return {
        "agent": agent.value if isinstance(agent, AgentName) else agent,
        "summary": (
            BLOCKED_AGENT_SUMMARY_ZH
            if response_language == "Chinese"
            else BLOCKED_AGENT_SUMMARY
        ),
        "rationale": [blocked_agent_rationale(response_language=response_language)],
        "confidence": 1.0,
        "data": {},
        "blocked": True,
        "policy_notes": _safe_policy_notes(policy_notes or []),
    }


def sanitize_blocked_agent_results(
    agent_results: list[Any], *, response_language: str = "English"
) -> list[dict[str, Any]]:
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
    return sanitized


def sanitize_blocked_audit(audit: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(audit)
    response_language = normalize_response_language(audit.get("response_language"))
    sanitized["response_language"] = response_language
    sanitized["routing_rationale"] = [
        BLOCKED_ROUTING_RATIONALE_ZH
        if response_language == "Chinese"
        else BLOCKED_ROUTING_RATIONALE
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
                BLOCKED_EDUCATIONAL_DISCLAIMER,
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
        if self.blocked:
            self.audit = sanitize_blocked_audit(self.audit)
            self.agent_results = [
                AgentResult.model_validate(item)
                for item in sanitize_blocked_agent_results(
                    self.agent_results, response_language=self.audit["response_language"]
                )
            ]
        return self
