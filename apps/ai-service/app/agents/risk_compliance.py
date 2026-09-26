import json
import re
from dataclasses import asdict

from app.agents.education_access import education_response_language
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
from app.core.telemetry import log_event, trace_method
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

# Decimal points and dotted abbreviations (e.g.) do not end an advice clause.
ADVICE_CLAUSE = r"(?:[^.!?;]|(?<=\d)\.(?=\d)|(?<=\b[a-z])\.)*"

BLOCKED_FINANCIAL_ADVICE_REGEXES = (
    (
        "brokerage_execution",
        re.compile(
            r"\b(?:log\s*in(?:to)?|sign\s*in(?:to)?|access)\s+"
            r"(?:to\s+)?(?:my|our|your|the user's)\s+(?:\w+\s+){0,3}"
            r"(?:brokerage|trading)\s+account\b|"
            r"\b(?:buy|purchase|sell|trade)\b[^.!?;]{0,70}\b(?:for me|on my behalf)\b|"
            r"(?:帮我|替我|代我|为你|帮你).{0,20}(?:登录|登入|下单|买入|卖出|交易)",
            re.IGNORECASE,
        ),
    ),
    (
        "product_recommendation",
        re.compile(
            r"\b(?:i|we)\s+(?:recommend|suggest|advise)\b" + ADVICE_CLAUSE +
            r"\b(?:buying|selling|holding|investing|buy|sell|hold|invest)\b|"
            r"\b(?:i|we)\s+(?:recommend|suggest|advise)\s+(?:this|that|the)\s+"
            r"(?:stock|share|bond|etf|fund|reit|investment\s+product|product)\b|"
            r"(?:^|[.!?;]\s*|\n\s*|:\s*)(?:buy|sell|hold)\s+(?:this|that|the)\s+"
            r"(?:stock|share|bond|etf|fund|reit|investment|product)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personalized_allocation",
        re.compile(
            r"\b(?:you should|i recommend(?: that)? you)\b" + ADVICE_CLAUSE +
            r"\b(?:allocate|invest|put)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "personalized_transaction",
        re.compile(
            r"\b(?:you should|i recommend(?: that)? you)\b" + ADVICE_CLAUSE +
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

CROSS_USER_DATA_ACCESS_REGEXES = (
    (
        "cross_user_reference",
        re.compile(
            r"\b(?:another|other|different)\s+"
            r"(?:user|users|person|people|member|members|"
            r"customer|customers|client|clients)\b"
            r"|\b(?:someone|somebody)\s+else'?s?\b"
            r"|\bother\s+people'?s?\b"
            r"|\bthird[-\s]party\b",
            re.IGNORECASE,
        ),
    ),
    (
        "third_party_request",
        re.compile(
            r"\b(?:show|tell|give|reveal|display|share|see|view|access|get|"
            r"find|look\s*up|pull\s*up|what(?:'s| is| are)|how\s+much)\b"
            r"[^.?!]{0,40}\b(?:her|his|their|hers|him)\b"
            r"[^.?!]{0,25}\b(?:income|salary|salaries|wage|wages|account|"
            r"balance|savings|transactions?|earnings|pay|payslip)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "cross_user_reference",
        re.compile(
            r"(?:其他|另一|别的|別的|别人|別人|他人)"
            r"(?:用户|用戶|人|会员|會員|客户|客戶)?"
            r"[^。？！]{0,20}"
            r"(?:收入|工资|工資|薪水|账户|帳戶|余额|餘額|存款|"
            r"财务|財務|资料|資料|数据|數據)"
        ),
    ),
    (
        "third_party_request",
        re.compile(
            r"(?:显示|顯示|告诉|告訴|查看|查询|查詢|给我|給我|透露|看看)"
            r"[^。？！]{0,20}(?:她|他|他们|他們)"
            r"[^。？！]{0,15}(?:收入|工资|工資|薪水|账户|帳戶|余额|餘額|存款)"
        ),
    ),
)


def cross_user_data_findings(text: str) -> list[str]:
    """Flag attempts to read another user's account or financial data.

    Only the user's own request is inspected. Approved specialist and policy
    evidence legitimately discusses "their goals" or "their risk" in general
    education, so scanning that generated text would false-positive; the
    boundary enforced here is that the coach never *attempts* to surface a
    third party's data in the first place.
    """
    normalized = " ".join(normalize_for_security_inspection(text).casefold().split())
    return list(
        dict.fromkeys(
            f"data_access:{label}"
            for label, pattern in CROSS_USER_DATA_ACCESS_REGEXES
            if pattern.search(normalized)
        )
    )


SAFE_POLICY_NOTES = (
    set(PII_PATTERNS)
    | {f"prompt_injection:{index}" for index in range(len(PROMPT_INJECTION_PATTERNS))}
    | {f"regulated_advice:{pattern}" for pattern in BLOCKED_FINANCIAL_ADVICE_PATTERNS}
    | {f"regulated_advice:{label}" for label, _ in BLOCKED_FINANCIAL_ADVICE_REGEXES}
    | {f"data_access:{label}" for label, _ in CROSS_USER_DATA_ACCESS_REGEXES}
    | {"policy_evidence:insufficient", "response_withheld"}
)


def contains_return_guarantee(text: str) -> bool:
    for sentence in re.split(r"(?<!\d)\.(?!\d)|[!?;\n]", text.lower()):
        for match in re.finditer(
            r"\bguarantee(?:d|s)?\s+(?:a\s+)?(?:\d+(?:\.\d+)?%\s+)?"
            r"(?:(?:annual|monthly|yearly|investment)\s+)?returns?\b", sentence,
        ):
            before, after = sentence[:match.start()], sentence[match.end():]
            negated = re.search(
                r"\b(?:no|not|never|without|cannot|can't)\s+"
                r"(?:(?:offer|provide|promise|any|a|can)\s+){0,3}$",
                before,
            ) or (re.search(
                r"\b(?:no|without|avoids?)\s+"
                r"(?:(?:personalized|personal|financial|investment|product)\s+){0,2}"
                r"(?:advice|recommendations?|instructions?)\s+(?:or|and)\s*$",
                before,
            ) and re.fullmatch(r"\s*(?:claims?|promises?)?\s*", after))
            risk_explanation = re.match(
                r"\s+(?:(?:is|are|can be)\s+)?(?:a\s+)?"
                r"(?:red flags?|warning signs?|misleading|unrealistic|impossible|scams?)\b",
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


def financial_advice_findings(text: str, *, is_request: bool = False) -> list[str]:
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
        if any(
            not (
                label == "brokerage_execution" and re.search(
                    r"(?:\b(?:cannot|can't|won't|never|not|don't)\s+|(?:不能|无法|不可以))$",
                    normalized[:match.start()],
                )
            ) and not (
                label in {"product_recommendation", "personalized_allocation", "personalized_transaction"}
                and is_educational_recommendation(match.group())
            ) and not (
                label == "personalized_product" and re.search(
                    r"\b(?:cannot|can't|does not|do not)\s+"
                    r"(?:determine|establish|assess|confirm|say)\s+(?:whether|if)\s+"
                    r"(?:(?:an?|any|the|this|that|investment|product|fund|etf|stock|bond|"
                    r"risk|level|of|or|is|are|would|be)\s+){1,16}$",
                    normalized[:match.start()],
                )
            )
            for match in pattern.finditer(normalized)
        )
    )
    if is_request and is_reported_guarantee_verification(normalized):
        findings = [f for f in findings if f != "regulated_advice:guaranteed return"]
    return findings


def is_educational_recommendation(text: str) -> bool:
    # Matches end at the LAST action in the sentence. An educational prefix
    # cannot exempt a later action ("learn before investing, then buy this ETF").
    return bool(re.fullmatch(
        r"(?:(?:i|we)\s+(?:recommend|suggest|advise)\s+"
        r"(?:that\s+)?(?:(?:you|investors)\s+)?|you should\s+)"
        r"(?:"
        r"(?:learn(?:ing)?(?: about)?|understand(?:ing)?|review(?:ing)?)\s+"
        r"(?:(?!\b(?:buy\w*|sell\w*|hold\w*|invest(?:ing)?|allocate|put|"
        r"recommend|suggest|advise|should|could|must|then|instead|but|however)\b)"
        r"(?:[^.!?;,]|(?<=\d)\.(?=\d)|(?<=\b[a-z])\.))*"
        r"\bbefore\s+(?:you\s+)?"
        r"|avoid(?:ing)?\s+)"
        r"(?:buying|selling|holding|investing|buy|sell|hold|invest|allocate|put)",
        text,
    ))


def is_reported_guarantee_verification(text: str) -> bool:
    claim = re.match(
        r"(?:my (?:friend|broker|adviser|advisor)|"
        r"(?:the|this) (?:provider|company|advertisement|advert|website))\s+"
        r"(?:says?|said|claims?)\s+(?:that\s+)?"
        r"(?:it|this|(?:an?|the|this) (?:investment|fund|offer|product))\s+"
        r"(?:guarantees?|(?:offers?|promises?|provides?|has)\s+(?:a\s+)?guaranteed)\s+"
        r"(?:a\s+)?(?:\d+(?:\.\d+)?%\s+)?"
        r"(?:(?:annual|monthly|yearly|investment)\s+)?returns?"
        r"(?:\s+(?:with no risk|without risk))?[.!?;,]\s*",
        text,
    )
    if not claim:
        return False
    questions = [part.strip() for part in re.split(r"[.!?;,]", text[claim.end():]) if part.strip()]
    # Every remaining clause must ask about verification or warning signs.
    # In particular, indirect requests such as "show me one" stay blocked.
    return bool(questions) and all(re.fullmatch(
        r"(?:is (?:it|this|that|the (?:provider|offer|claim)) (?:legitimate|true|a scam|a fraud)|"
        r"(?:how can i|can you) (?:check|verify) "
        r"(?:it|this|that|whether (?:it|this) is legitimate)|"
        r"what (?:are|would be) (?:the )?(?:warning signs|red flags)|"
        r"(?:what|which) (?:warning signs|red flags) should i (?:look for|check))",
        question,
    ) for question in questions)


def contains_buy_sell_instruction(text: str) -> bool:
    for sentence in re.split(r"[.!?;\n]", text):
        for match in re.finditer(r"\bbuy or sell\b", sentence):
            before, after = sentence[:match.start()], sentence[match.end():]
            # The approved ETF guide describes a manager's execution constraints.
            manager_constraint = re.search(
                r"\b(?:manager(?:(?:'s|’s)? inability to| may be unable to| cannot)|"
                r"inability(?: of (?:the )?(?:(?:etf|fund) )?manager)? to)\s*$", before
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


@trace_method
def withhold_agent_result(
    result: AgentResult, *, response_language: str = "English"
) -> AgentResult:
    return AgentResult(
        agent=result.agent,
        summary=(
            "生成内容未通过最终安全审查，已被隐藏。"
            if response_language == "Chinese"
            else "Generated content was withheld by the final safety review."
        ),
        rationale=[
            "最终安全审查已拦截此回复。"
            if response_language == "Chinese"
            else "The final safety review blocked this response."
        ],
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

    @trace_method
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
        hard_policy_findings = list(dict.fromkeys([
            *financial_advice_findings(request.message, is_request=True),
            *(
                finding
                for text in generated_fields
                for finding in financial_advice_findings(text)
            ),
        ]))
        policy_notes.extend(hard_policy_findings)
        # Refuse cross-user data-access attempts deterministically on the
        # request itself, before any retrieval or model call, so social
        # engineering cannot coax another user's data into a generated answer.
        data_access_findings = cross_user_data_findings(request.message)
        policy_notes.extend(data_access_findings)

        if (
            not decision.allowed
            or generated_decision.findings
            or hard_policy_findings
            or data_access_findings
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
        log_event(
            "rag.policy.context.ready", accepted_chunk_count=len(contexts),
            source_count=len(policy_sources), corpus_version=policy_corpus_version,
            evidence_status="grounded" if contexts else "insufficient",
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
                + "\nWrite summary, rationale and policy_notes in "
                + education_response_language(decision.sanitized_text)
                + "."
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
                                    "fallback_topics",
                                    "general_knowledge",
                                    # Deterministic tool outputs are evidence too;
                                    # the request text may omit saved financial inputs.
                                    "income",
                                    "recurring_expenses",
                                    "disposable_income",
                                    "needs",
                                    "wants",
                                    "savings",
                                    "method",
                                    "spending_context",
                                    "projections",
                                    "monthly_savings_capacity",
                                    "feasibility",
                                    "category_totals",
                                    "transaction_count",
                                    "category_trends",
                                    "temporal_patterns",
                                    "anomalies",
                                    "data_quality",
                                    "months_analyzed",
                                    "needs_input",
                                    "questions",
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
