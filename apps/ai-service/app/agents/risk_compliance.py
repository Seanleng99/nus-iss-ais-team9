import json

from app.core.guardrails import ADVISORY_DISCLAIMER, inspect_prompt
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentResult,
    CoachRequest,
    ComplianceDecision,
)
from app.models.gateway import ModelGateway
from app.models.structured import parse_structured_response
from app.tools.registry import call_retrieval_tool

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
    ) -> None:
        self.gateway = gateway
        self.prompts = prompts
        self.temperature = temperature
        self.max_tokens = max_tokens

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

        contexts = call_retrieval_tool(
            self.name,
            "trusted_retriever",
            decision.sanitized_text,
        )
        raw = self.gateway.generate(
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
                        }
                        for result in results
                    ],
                },
                ensure_ascii=True,
            ),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        review = parse_structured_response(raw, ComplianceDecision)
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
                "sources": [item["source_id"] for item in contexts],
                "contexts": contexts,
            },
        )
