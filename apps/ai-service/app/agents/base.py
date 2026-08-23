import json
from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.core.guardrails import inspect_prompt, require_explanation
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentNarrative,
    AgentResult,
    AgentTask,
    CapabilityResult,
    CompletedInvocation,
    DependencyRequest,
    NeedsDependencyInvocation,
)
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

    def run_task(self, task: AgentTask) -> CompletedInvocation | NeedsDependencyInvocation:
        decision = inspect_prompt(task.sanitized_message)
        if not decision.allowed:
            return CompletedInvocation(
                result=AgentResult(
                    agent=self.name,
                    summary="Request blocked before agent execution.",
                    rationale=["The request matched prompt-injection safety checks."],
                    confidence=1.0,
                    blocked=True,
                    policy_notes=decision.findings,
                )
            )

        dependencies = self._dependency_requests(task)
        if dependencies:
            return NeedsDependencyInvocation(dependency_requests=list(dependencies))

        grounding = self._ground(task, decision.sanitized_text)
        if grounding.get("evidence_status") == "insufficient":
            result = AgentResult(
                agent=self.name,
                summary=(
                    "The approved knowledge base does not contain enough information "
                    "to answer this question."
                ),
                rationale=["No relevant approved source was retrieved."],
                confidence=1.0,
                data=grounding,
            )
            return CompletedInvocation(
                result=result,
                capabilities=self._capabilities(task, grounding, result),
            )
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
        return CompletedInvocation(
            result=result,
            capabilities=self._capabilities(task, grounding, result),
        )

    def _dependency_requests(self, task: AgentTask) -> Sequence[DependencyRequest]:
        del task
        return ()

    def _capabilities(
        self,
        task: AgentTask,
        grounding: dict,
        result: AgentResult,
    ) -> list[CapabilityResult]:
        del task, grounding, result
        return []

    @abstractmethod
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        raise NotImplementedError
