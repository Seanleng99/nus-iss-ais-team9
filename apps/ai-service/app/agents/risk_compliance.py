import json
import re
from dataclasses import asdict

from app.core.citations import citation_contract, validate_citations
from app.core.guardrails import (
    ADVISORY_DISCLAIMER,
    PII_PATTERNS,
    PROMPT_INJECTION_PATTERNS,
    inspect_prompt,
    normalize_for_security_inspection,
    sanitize_rag_document,
    validate_tool_permission,
)
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentResult,
    CoachRequest,
    ComplianceDecision,
    SourceCitation,
)
from app.models.gateway import ModelGateway
from app.models.structured import generate_structured_response
from app.rag.policy import PolicyRetriever
from app.rag.retriever import MAX_EDUCATION_CHUNK_CHARACTERS

BLOCKED_FINANCIAL_ADVICE_PATTERNS = [
    "guaranteed return",
    "which stock should i buy",
    "tell me exactly what to invest in",
    "buy or sell",
]

BLOCKED_FINANCIAL_ADVICE_REGEXES = (
    (
        "personalized_allocation",
        re.compile(
            r"\b(?:you should|i recommend(?: that)? you)\b.{0,80}"
            r"\b(?:allocate|invest|put)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personalized_transaction",
        re.compile(
            r"\b(?:you should|i recommend(?: that)? you)\b.{0,80}"
            r"\b(?:buy|sell|hold)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personalized_product",
        re.compile(
            r"\b(?:best|right|suitable)\b.{0,30}\bfor you\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personalized_product_selection",
        re.compile(
            r"\b(?:which|what)\s+"
            r"(?:stock|share|bond|etf|fund|reit|investment|product)\b"
            r".{0,40}\b(?:buy|choose|pick|invest in)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personalized_transaction_request",
        re.compile(
            r"\bshould\s+i\b.{0,20}\b(?:buy|sell|hold|choose|invest in)\b"
            r".{0,40}\b(?:stock|share|bond|etf|fund|reit|investment|product)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personalized_investment_instruction",
        re.compile(r"(?:建议你|你应该|你应当).{0,40}(?:买入|卖出|持有|投资于|投入|配置)"),
    ),
)

SAFE_POLICY_NOTES = (
    set(PII_PATTERNS)
    | {f"prompt_injection:{index}" for index in range(len(PROMPT_INJECTION_PATTERNS))}
    | {f"regulated_advice:{pattern}" for pattern in BLOCKED_FINANCIAL_ADVICE_PATTERNS}
    | {f"regulated_advice:{label}" for label, _ in BLOCKED_FINANCIAL_ADVICE_REGEXES}
    | {"policy_evidence:insufficient", "response_withheld"}
)


def contains_return_guarantee(text: str) -> bool:
    for sentence in re.split(r"[.!?;\n]", text.lower()):
        for match in re.finditer(r"\bguaranteed returns?\b", sentence):
            before, after = sentence[:match.start()], sentence[match.end():]
            negated = re.search(
                r"\b(?:no|not|never|without)\s+(?:(?:offer|provide|promise|any|a)\s+){0,3}$",
                before,
            )
            risk_explanation = re.match(
                r"\s+(?:(?:is|are|can be)\s+)?(?:a\s+)?"
                r"(?:red flag|warning sign|misleading|unrealistic|impossible|scam)\b",
                after,
            )
            policy_assessment = re.search(
                r"\b(?:avoids? (?:making )?(?:any )?claims about|"
                r"(?:does|do) not make (?:any )?claims about|"
                r"makes? no claims about|"
                r"educational warnings or negations about)\s*$",
                before,
            )
            if not negated and not risk_explanation and not policy_assessment:
                return True
        if re.search(r"\breturns?\s+(?:is|are|will be)\s+guaranteed\b", sentence):
            return True
    return False


def financial_advice_findings(text: str) -> list[str]:
    normalized = " ".join(normalize_for_security_inspection(text).casefold().split())
    findings = [
        f"regulated_advice:{pattern}"
        for pattern in BLOCKED_FINANCIAL_ADVICE_PATTERNS
        if (
            contains_return_guarantee(normalized)
            if pattern == "guaranteed return" else
            contains_buy_sell_instruction(normalized) if pattern == "buy or sell"
            else pattern in normalized
        )
    ]
    findings.extend(
        f"regulated_advice:{label}"
        for label, pattern in BLOCKED_FINANCIAL_ADVICE_REGEXES
        if pattern.search(normalized)
    )
    return findings


def contains_buy_sell_instruction(text: str) -> bool:
    for sentence in re.split(r"[.!?;\n]", text):
        for match in re.finditer(r"\bbuy or sell\b", sentence):
            before, after = sentence[:match.start()], sentence[match.end():]
            # The approved ETF guide describes a manager's execution constraints.
            manager_constraint = re.search(
                r"\bmanager(?:(?:'s|’s)? inability to| may be unable to| cannot)\s*$", before
            )
            component_stocks = re.match(r"\s+(?:the\s+)?component stocks\b", after)
            policy_negation = re.search(
                r"\b(?:no|not|never|without|avoids?)\s+"
                r"(?:(?:provide|providing|give|giving|personalized|any|a)\s+){0,4}$",
                before,
            ) and re.match(r"\s+(?:or allocation\s+)?instructions?\b", after)
            brokerage_description = re.search(
                r"\b(?:brokerage commissions?|trading fees?) "
                r"(?:may apply|apply|are charged) when (?:you|investors)\s*$",
                before,
            ) and re.match(r"\s+(?:etfs?|shares|stocks)\b", after)
            if not (
                (manager_constraint and component_stocks)
                or policy_negation or brokerage_description
            ):
                return True
    return False


def withhold_agent_result(result: AgentResult) -> AgentResult:
    return AgentResult(
        agent=result.agent,
        summary="Generated content was withheld by the final safety review.",
        rationale=["The final safety review blocked this response."],
        confidence=1.0,
        blocked=True,
        policy_notes=[note for note in result.policy_notes if note in SAFE_POLICY_NOTES],
        data={
            key: result.data[key]
            for key in ("evidence_status", "policy_evidence_status")
            if result.data.get(key) in ("grounded", "partial", "insufficient")
        },
    )


class RiskComplianceAgent:
    name = AgentName.RISK_COMPLIANCE

    def __init__(
        self,
        gateway: ModelGateway,
        prompts: PromptCatalog,
        temperature: float,
        max_tokens: int,
        policy_retriever: PolicyRetriever,
    ) -> None:
        self.gateway = gateway
        self.prompts = prompts
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.policy_retriever = policy_retriever

    def validate(
        self,
        request: CoachRequest,
        results: list[AgentResult],
        draft_answer: str,
        routing_rationale: list[str] | None = None,
    ) -> AgentResult:
        decision = inspect_prompt(request.message)
        policy_notes = list(decision.findings)
        generated_fields = [
            draft_answer,
            *(routing_rationale or []),
            *(
                text
                for result in results
                for text in (
                    result.summary, *result.rationale,
                    *result.data.get("uncertainties", []),
                )
            ),
        ]
        generated_text = "\n".join(generated_fields)
        generated_decision = inspect_prompt(generated_text)
        policy_notes.extend(generated_decision.findings)
        hard_policy_findings = list(dict.fromkeys(
            finding
            for text in [request.message, *generated_fields]
            for finding in financial_advice_findings(text)
        ))
        policy_notes.extend(hard_policy_findings)

        if (
            not decision.allowed
            or generated_decision.findings
            or hard_policy_findings
            or any(result.blocked for result in results)
        ):
            return AgentResult(
                agent=self.name,
                summary="The response was blocked by deterministic safety controls.",
                rationale=["A hard policy rule takes precedence over model-generated content."],
                confidence=1.0,
                blocked=True,
                policy_notes=policy_notes,
                data={"disclaimer": ADVISORY_DISCLAIMER},
            )

        validate_tool_permission(self.name, "policy_retriever")
        contexts = []
        for item in self.policy_retriever.retrieve(decision.sanitized_text):
            context = asdict(item)
            metadata_inspection = sanitize_rag_document(
                f"{context['title']} {context['issuing_organization']}"
            )
            if (
                metadata_inspection.findings
                or not context["text"].strip()
                or len(context["text"]) > MAX_EDUCATION_CHUNK_CHARACTERS
            ):
                continue
            inspection = sanitize_rag_document(context["text"])
            context["text"] = inspection.sanitized_text
            context["findings"] = list(
                dict.fromkeys([*context["findings"], *inspection.findings])
            )
            if any(
                finding.startswith("indirect_prompt_injection:")
                for finding in context["findings"]
            ):
                continue
            contexts.append(context)
        policy_sources = [
            {
                key: context[key]
                for key in (
                    "source_id",
                    "title",
                    "issuing_organization",
                    "canonical_url",
                    "published_at",
                    "document_version",
                    "checksum",
                    "corpus_version",
                    "review_due_at",
                )
            }
            for context in contexts
        ]
        policy_corpus_version = getattr(
            self.policy_retriever,
            "expected_corpus_version",
            getattr(self.policy_retriever, "corpus_version", None),
        )
        if not contexts:
            return AgentResult(
                agent=self.name,
                summary="The response was blocked because approved policy evidence was unavailable.",
                rationale=[
                    "Risk and Compliance fails closed when no current governed policy is retrieved."
                ],
                confidence=1.0,
                blocked=True,
                policy_notes=["policy_evidence:insufficient"],
                data={
                    "disclaimer": ADVISORY_DISCLAIMER,
                    "policy_evidence_status": "insufficient",
                    "policy_corpus_version": policy_corpus_version,
                    "policy_sources": [],
                },
            )
        review_sources = [
            SourceCitation.model_validate(source)
            for source in [
                *policy_sources,
                *(
                    source for result in results for source in result.data.get("sources", [])
                    if source["source_id"] in result.data.get(
                        "cited_source_ids",
                        [item["source_id"] for item in result.data.get("sources", [])],
                    )
                ),
            ]
        ]

        def validate_review(review: ComplianceDecision) -> ComplianceDecision:
            for text in (review.summary, *review.rationale, *review.policy_notes):
                validate_citations(text, review_sources)
            return review

        review = generate_structured_response(
            self.gateway,
            response_type=ComplianceDecision,
            system_prompt=(
                self.prompts.get("risk_compliance")
                + "\nReturn a short policy verdict only. Do not rewrite the answer "
                "or introduce any financial facts. Keep rationale and policy_notes "
                "to at most two short assessment sentences each."
                + citation_contract(review_sources)
            ),
            user_prompt=json.dumps(
                {
                    "message": decision.sanitized_text,
                    "draft_answer": draft_answer,
                    "routing_rationale": routing_rationale or [],
                    "policy_context": contexts,
                    "agent_results": [
                        {
                            "agent": result.agent.value,
                            "summary": result.summary,
                            "rationale": result.rationale,
                            "data": {
                                key: result.data[key]
                                for key in (
                                    "evidence_status",
                                    "sources",
                                    "contexts",
                                    "cited_source_ids",
                                    "uncertainties",
                                    "query_topics",
                                    "unanswered_topics",
                                )
                                if key in result.data
                            },
                        }
                        for result in results
                    ],
                },
                ensure_ascii=False,
            ),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            validate_response=validate_review,
        )
        output_decision = inspect_prompt(
            " ".join([review.summary, *review.rationale, *review.policy_notes])
        )
        output_findings = list(dict.fromkeys([
            *output_decision.findings,
            *(
                finding
                for text in [review.summary, *review.rationale, *review.policy_notes]
                for finding in financial_advice_findings(text)
            ),
        ]))
        compliance_data = {
            "disclaimer": ADVISORY_DISCLAIMER,
            "policy_evidence_status": "grounded",
            "policy_corpus_version": policy_corpus_version,
            "policy_sources": policy_sources,
            "policy_contexts": contexts,
        }
        if output_findings:
            return AgentResult(
                agent=self.name,
                summary="Compliance output was blocked by safety controls.",
                rationale=[
                    "Generated compliance content matched output safety checks."
                ],
                confidence=1.0,
                blocked=True,
                policy_notes=list(
                    dict.fromkeys(
                        [*review.policy_notes, *output_findings]
                    )
                ),
                data=compliance_data,
            )
        return AgentResult(
            agent=self.name,
            summary=review.summary,
            rationale=review.rationale,
            confidence=review.confidence,
            blocked=review.blocked,
            policy_notes=review.policy_notes,
            data=compliance_data,
        )
