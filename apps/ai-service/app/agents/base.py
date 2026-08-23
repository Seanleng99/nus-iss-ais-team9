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
    DependencyPlanningDecision,
    DependencyRequest,
    DependencyRequestDraft,
    NeedsDependencyInvocation,
    NeedsInputInvocation,
)
from app.models.gateway import ModelGateway, ModelGatewayError
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

    dependency_planning_enabled = False

    def run_task(
        self, task: AgentTask
    ) -> CompletedInvocation | NeedsDependencyInvocation | NeedsInputInvocation:
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

        preflight = self._preflight(task, decision.sanitized_text)
        if preflight is not None:
            return preflight

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

    def _dependency_options(self, task: AgentTask) -> Sequence[DependencyRequestDraft]:
        del task
        return ()

    def _missing_input_questions(self, task: AgentTask) -> Sequence[str]:
        del task
        return ()

    def _preflight(
        self,
        task: AgentTask,
        sanitized_message: str,
    ) -> NeedsDependencyInvocation | NeedsInputInvocation | None:
        if self.prompts.version == "v2":
            dependencies = list(self._dependency_requests(task))
            return (
                NeedsDependencyInvocation(dependency_requests=dependencies)
                if dependencies
                else None
            )
        if not self.dependency_planning_enabled:
            return None

        options = list(self._dependency_options(task))
        missing_questions = list(self._missing_input_questions(task))
        if not options and not missing_questions:
            return None
        raw = self.gateway.generate(
            system_prompt=self.prompts.get("dependency_planner"),
            user_prompt=json.dumps(
                {
                    "agent": self.name.value,
                    "message": sanitized_message,
                    "context_features": task.context_features,
                    "resolved_capabilities": [
                        item.value for item in task.resolved_dependencies
                    ],
                    "allowed_requests": [
                        option.model_dump(mode="json") for option in options
                    ],
                    "missing_input_questions": missing_questions,
                },
                ensure_ascii=True,
            ),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        plan = parse_structured_response(raw, DependencyPlanningDecision)
        if plan.status == "ready":
            return None
        if plan.status == "needs_input":
            allowed_questions = set(missing_questions)
            if not plan.questions or any(
                question not in allowed_questions for question in plan.questions
            ):
                raise ModelGatewayError(
                    "The dependency planner requested unauthorized user input."
                )
            return NeedsInputInvocation(
                reason_code=plan.reason_code or "MISSING_REQUIRED_INPUT",
                questions=plan.questions,
            )

        allowed = {option.capability: option for option in options}
        requests: list[DependencyRequest] = []
        seen: set = set()
        for requested in plan.requests:
            option = allowed.get(requested.capability)
            if option is None or requested.capability in seen:
                raise ModelGatewayError(
                    "The dependency planner requested an unauthorized capability."
                )
            seen.add(requested.capability)
            requests.append(
                DependencyRequest(
                    requester_task_id=task.task_id,
                    requester=self.name,
                    capability=requested.capability,
                    reason_code=requested.reason_code,
                    required_output_fields=(
                        requested.required_output_fields
                        or option.required_output_fields
                    ),
                    required=requested.required,
                )
            )
        return NeedsDependencyInvocation(dependency_requests=requests)

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
