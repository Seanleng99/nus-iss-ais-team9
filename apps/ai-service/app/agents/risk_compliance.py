import json
from dataclasses import asdict

from app.core.guardrails import (
    ADVISORY_DISCLAIMER,
    inspect_prompt,
    sanitize_rag_document,
    validate_tool_permission,
)
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentResult,
    CoachRequest,
    ComplianceDecision,
)
from app.models.gateway import ModelGateway
from app.models.structured import generate_structured_response
from app.rag.policy import PolicyRetriever

BLOCKED_FINANCIAL_ADVICE_PATTERNS = [
    "guaranteed return",
    "which stock should i buy",
    "tell me exactly what to invest in",
    "buy or sell",
]


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
    ) -> AgentResult:
        decision = inspect_prompt(request.message)
        policy_notes = list(decision.findings)
        hard_policy_findings: list[str] = []
        inspected_text = " ".join(
            [request.message, draft_answer, *(result.summary for result in results)]
        ).lower()
        for pattern in BLOCKED_FINANCIAL_ADVICE_PATTERNS:
            if pattern in inspected_text:
                finding = f"regulated_advice:{pattern}"
                policy_notes.append(finding)
                hard_policy_findings.append(finding)

        if not decision.allowed or hard_policy_findings or any(result.blocked for result in results):
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
            inspection = sanitize_rag_document(context["text"])
            context["text"] = inspection.sanitized_text
            context["findings"] = list(
                dict.fromkeys([*context["findings"], *inspection.findings])
            )
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
        review = generate_structured_response(
            self.gateway,
            response_type=ComplianceDecision,
            system_prompt=self.prompts.get("risk_compliance"),
            user_prompt=json.dumps(
                {
                    "message": decision.sanitized_text,
                    "draft_answer": draft_answer,
                    "policy_context": contexts,
                    "agent_results": [
                        {
                            "agent": result.agent.value,
                            "summary": result.summary,
                            "rationale": result.rationale,
                            "data": {
                                key: result.data[key]
                                for key in ("evidence_status", "sources", "contexts")
                                if key in result.data
                            },
                        }
                        for result in results
                    ],
                },
                ensure_ascii=True,
            ),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        output_decision = inspect_prompt(
            " ".join([review.summary, *review.rationale, *review.policy_notes])
        )
        blocked = review.blocked or not output_decision.allowed
        return AgentResult(
            agent=self.name,
            summary=review.summary,
            rationale=review.rationale,
            confidence=review.confidence,
            blocked=blocked,
            policy_notes=review.policy_notes + output_decision.findings,
            data={
                "disclaimer": ADVISORY_DISCLAIMER,
                "policy_evidence_status": "grounded",
                "policy_corpus_version": policy_corpus_version,
                "policy_sources": policy_sources,
                "policy_contexts": contexts,
            },
        )
