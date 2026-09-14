import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app.core.schemas import AgentName
from app.core.telemetry import trace_method

PII_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "phone": re.compile(r"\b(?:\+65\s*)?[689]\d{3}\s?\d{4}\b"),
    "nric_like": re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE),
    "card_like": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
}

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"\bignore (all )?(previous|above|system|developer) instructions\b", re.IGNORECASE),
    re.compile(r"\breveal (the )?(system prompt|hidden instructions|developer message)\b", re.IGNORECASE),
    re.compile(r"\bdisregard (policy|guardrails|safety rules)\b", re.IGNORECASE),
    re.compile(r"\bexfiltrate\b|\bapi[_ -]?key\b|\bpassword\b|\bsecret\b", re.IGNORECASE),
    re.compile(
        r"\b(?:act|behave|respond)\s+as\s+(?:the\s+)?"
        r"(?:system|developer|administrator)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:override|bypass|disable)\b.{0,40}"
        r"\b(?:safety|guardrails?|policy|instructions?|filters?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:print|show|dump|expose)\b.{0,40}"
        r"\b(?:system prompt|hidden instructions|developer message|secrets?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"<\s*/?\s*(?:system|developer|assistant)\s*>|"
        r"\[\s*/?\s*INST\s*\]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|\n)\s*(?:system|developer|assistant)\s*:",
        re.IGNORECASE,
    ),
    re.compile(r"(?:忽略|无视|忽視|無視).{0,12}(?:之前|以前|系统|系統|开发者|開發者).{0,8}(?:指令|提示|规则|規則)"),
    re.compile(r"(?:输出|輸出|显示|顯示|透露|泄露|洩露).{0,12}(?:系统提示|系統提示|隐藏指令|隱藏指令)"),
]

ADVISORY_DISCLAIMER = (
    "This is general financial education, not regulated financial advice. "
    "Consider consulting a licensed financial adviser for personal investment decisions."
)


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    sanitized_text: str
    findings: list[str]


def redact_sensitive_text(text: str) -> tuple[str, list[str]]:
    redacted = text
    findings: list[str] = []
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(redacted):
            findings.append(label)
            redacted = pattern.sub(f"[REDACTED_{label.upper()}]", redacted)
    return redacted, findings


def normalize_for_security_inspection(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Cf"
    )


@trace_method
def inspect_prompt(text: str) -> GuardrailDecision:
    sanitized, pii_findings = redact_sensitive_text(text)
    inspected = normalize_for_security_inspection(sanitized)
    injection_findings = [
        f"prompt_injection:{idx}"
        for idx, pattern in enumerate(PROMPT_INJECTION_PATTERNS)
        if pattern.search(inspected)
    ]
    findings = pii_findings + injection_findings
    return GuardrailDecision(
        allowed=not injection_findings,
        sanitized_text=sanitized,
        findings=findings,
    )


@trace_method
def sanitize_rag_document(text: str) -> GuardrailDecision:
    sanitized, pii_findings = redact_sensitive_text(text)
    findings = list(pii_findings)
    inspected = normalize_for_security_inspection(sanitized)
    for idx, pattern in enumerate(PROMPT_INJECTION_PATTERNS):
        if pattern.search(inspected):
            findings.append(f"indirect_prompt_injection:{idx}")
    if len(findings) > len(pii_findings):
        sanitized = "[REMOVED_UNTRUSTED_INSTRUCTION]"
    return GuardrailDecision(allowed=True, sanitized_text=sanitized, findings=findings)


TOOL_ALLOWLIST: dict[AgentName, set[str]] = {
    AgentName.SPENDING: {"transaction_summarizer"},
    AgentName.BUDGET: {"budget_calculator", "education_retriever"},
    AgentName.GOAL_STRATEGY: {"goal_projection", "education_retriever"},
    AgentName.INVESTMENT_EDUCATION: {"education_retriever"},
    AgentName.RISK_COMPLIANCE: {"policy_checker", "policy_retriever"},
}


@trace_method
def validate_tool_permission(agent: AgentName, tool_name: str) -> None:
    allowed = TOOL_ALLOWLIST.get(agent, set())
    if tool_name not in allowed:
        raise PermissionError(f"{agent.value} cannot call tool {tool_name}")


def require_explanation(result_rationale: Iterable[str]) -> list[str]:
    rationale = [item for item in result_rationale if item.strip()]
    if rationale:
        return rationale
    return ["No detailed rationale was generated; response should be reviewed before release."]
