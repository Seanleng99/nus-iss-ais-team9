import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from coach_i18n import input_pattern, translate

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
    re.compile(
        # Look ahead so a harmless warning cannot consume a second, unsafe
        # credential directive in the same sentence.
        r"(?=(?:\bexfiltrate\b|"
        r"(?P<credential_action>\b(?:reveal|dump|print|expose|retrieve|use|store|send)\b)"
        r"[^.!?;]{0,50}\b(?P<credential_object>api[_ -]?keys?|passwords?|secrets?)\b|"
        r"\b(?:my|our|the)\s+(?:api[_ -]?key|password)\s*(?:is|:|=)\s*\S+))",
        re.IGNORECASE,
    ),
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
    re.compile(input_pattern("ai.core.guardrails.ignore_instructions")),
    re.compile(input_pattern("ai.core.guardrails.reveal_prompt")),
    # Explicit record-concealment directives are safeguard evasion. Ordinary
    # privacy deletion and questions about record integrity remain allowed.
    re.compile(
        r"(?:^|[.!?;\n]|\b(?:and|then)\b)\s*"
        r"(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
        r"(?:change|rewrite|alter|falsify|doctor|edit|delete|erase)\b"
        r"[^.!?;]{0,60}\b(?:transcript|records?|history|audit (?:log|trail))\b"
        r"[^.!?;]{0,60}\b(?:hide|conceal|cover up)\b",
        re.IGNORECASE,
    ),
    re.compile(
        input_pattern("ai.core.guardrails.conceal_record_tampering")
    ),
]

ADVISORY_DISCLAIMER = translate("safety.educational_disclaimer", "en")

_CREDENTIAL_SAFETY_NEGATION = re.compile(
    r"\b(?:never|(?:do|must|should)\s+not|don['\N{RIGHT SINGLE QUOTATION MARK}]t)"
    r"\s+(?:ever\s+)?$", re.IGNORECASE,
)
_GENERIC_PASSWORD_HYGIENE = re.compile(
    r"use\s+(?:a\s+)?"
    r"(?:(?:strong|unique|long|complex|random|secure)[\s,]+){1,4}passwords?$",
    re.IGNORECASE,
)


def _has_injection_match(pattern: re.Pattern[str], text: str) -> bool:
    if "credential_action" not in pattern.groupindex:
        return pattern.search(text) is not None
    for match in pattern.finditer(text):
        action = match.group("credential_action")
        # Exfiltration and literal credential disclosures are never waived.
        if action is None:
            return True
        if _CREDENTIAL_SAFETY_NEGATION.search(text[max(0, match.start() - 40):match.start()]):
            continue
        if action.casefold() == "use" and match.group("credential_object").casefold() in {
            "password", "passwords",
        }:
            noun_phrase = text[match.start():match.end("credential_object")]
            remainder = text[match.end("credential_object"):]
            # These generic hygiene objects do not ask for a user's secret.
            # Other credential verbs are inspected independently, even when
            # the same sentence also recommends a strong password or manager.
            if _GENERIC_PASSWORD_HYGIENE.fullmatch(noun_phrase) and not re.match(
                r"\s*(?::|=|is\b|from\b|of\b|belonging\b)", remainder, re.IGNORECASE,
            ):
                continue
            if re.fullmatch(r"use\s+a\s+password", noun_phrase, re.IGNORECASE) and re.match(
                r"\s+manager\b", remainder, re.IGNORECASE,
            ):
                continue
        return True
    return False


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    sanitized_text: str
    findings: list[str]


def redact_sensitive_text(text: str) -> tuple[str, list[str]]:
    redacted = text
    findings: list[str] = []
    for label, pattern in PII_PATTERNS.items():
        matches = list(pattern.finditer(redacted))
        # Explicit monetary tokens are amounts, not telephone/card identifiers.
        protected = [(match.start(), match.end()) for match in re.finditer(
            r"(?i)(?:SGD|USD|S\$|US\$|\$)\s*\d[\d,]*(?:\.\d+)?", redacted
        )] if label in {"phone", "card_like"} else []
        matches = [match for match in matches if not any(
            start <= match.start() and match.end() <= end for start, end in protected
        )]
        if matches:
            findings.append(label)
            for match in reversed(matches):
                redacted = redacted[:match.start()] + f"[REDACTED_{label.upper()}]" + redacted[match.end():]
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
        if _has_injection_match(pattern, inspected)
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
        if _has_injection_match(pattern, inspected):
            findings.append(f"indirect_prompt_injection:{idx}")
    if len(findings) > len(pii_findings):
        sanitized = "[REMOVED_UNTRUSTED_INSTRUCTION]"
    return GuardrailDecision(allowed=True, sanitized_text=sanitized, findings=findings)


# Direct tool execution only; capability requests are authorized separately by
# CapabilityRegistry before the Orchestrator invokes the permitted provider.
TOOL_ALLOWLIST: dict[AgentName, set[str]] = {
    AgentName.SPENDING: {"transaction_summarizer"},
    AgentName.BUDGET: {"budget_calculator", "budget_planner"},
    AgentName.GOAL_STRATEGY: {"goal_projection", "emergency_fund_summary"},
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
