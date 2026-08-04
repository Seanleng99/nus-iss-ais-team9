import json
from abc import ABC, abstractmethod

from app.core.guardrails import inspect_prompt, require_explanation
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentName, AgentNarrative, AgentResult, CoachRequest
from app.models.gateway import ModelGateway
from app.models.structured import parse_structured_response


class BaseAgent(ABC):
    name: AgentName
    prompt_id: str

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

    def run(self, request: CoachRequest) -> AgentResult:
        decision = inspect_prompt(request.message)
        if not decision.allowed:
            return AgentResult(
                agent=self.name,
                summary="Request blocked before agent execution.",
                rationale=["The request matched prompt-injection safety checks."],
                confidence=1.0,
                blocked=True,
                policy_notes=decision.findings,
            )
        grounding = self._ground(request, decision.sanitized_text)
        raw = self.gateway.generate(
            system_prompt=self.prompts.get(self.prompt_id),
            user_prompt=json.dumps(
                {"message": decision.sanitized_text, "grounding": grounding},
                ensure_ascii=True,
            ),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        narrative = parse_structured_response(raw, AgentNarrative)
        result = AgentResult(
            agent=self.name,
            summary=narrative.summary,
            rationale=narrative.rationale,
            confidence=narrative.confidence,
            data=grounding,
        )
        result.rationale = require_explanation(result.rationale)
        return result

    @abstractmethod
    def _ground(self, request: CoachRequest, sanitized_message: str) -> dict:
        raise NotImplementedError
