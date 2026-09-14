import json
import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from contextvars import copy_context
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter, sleep
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.base import BaseAgent
from app.agents.budget import BudgetAgent
from app.agents.education_access import (
    apply_education_scope,
    build_minimal_education_query,
    education_gap_message,
    education_response_language,
    should_request_education_context,
)
from app.agents.goal_strategy import GoalStrategyAgent
from app.agents.investment_education import InvestmentEducationAgent
from app.agents.risk_compliance import RiskComplianceAgent, withhold_agent_result
from app.agents.spending import SpendingAgent
from app.capabilities.registry import CapabilityRegistry, CapabilityRegistryError
from app.core.citations import citation_contract, render_citations, validate_citations
from app.core.config import Settings
from app.core.config import settings as runtime_settings
from app.core.guardrails import ADVISORY_DISCLAIMER, inspect_prompt, validate_tool_permission
from app.core.observability import get_correlation_id
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    AgentTaskStatus,
    AuditEvent,
    CapabilityDefinition,
    CapabilityName,
    CapabilityProviderType,
    CapabilityResult,
    CoachRequest,
    CoachResponse,
    CompletedInvocation,
    DependencyEdge,
    DependencyRequest,
    DependencyResolution,
    FailedInvocation,
    NeedsDependencyInvocation,
    NeedsInputInvocation,
    RouterDecision,
    SourceCitation,
    SynthesisDecision,
)
from app.models.gateway import (
    ModelGateway,
    ModelGatewayError,
    TracingModelGateway,
    create_model_gateway,
)
from app.models.structured import generate_structured_response
from app.rag.policy import PolicyRetriever, create_policy_retriever
from app.rag.request_cache import RequestScopedEducationRetriever
from app.rag.retriever import (
    EducationRetriever,
    RetrievalError,
    build_education_context,
    create_education_retriever,
)

logger = logging.getLogger("service.ai.workflow")

SAFE_WORKFLOW_DETAIL_KEYS = {
    "accepted_chunk_count",
    "agent",
    "agent_result_count",
    "allowed",
    "attempt",
    "attempts",
    "blocked",
    "capabilities",
    "capability",
    "corpus_version",
    "duration_ms",
    "error_code",
    "evidence_status",
    "finding_count",
    "input_fingerprint",
    "model_call_count",
    "model_input_tokens",
    "model_output_tokens",
    "policy_corpus_version",
    "policy_corpus_versions",
    "policy_note_count",
    "policy_source_count",
    "query_topics",
    "reason_code",
    "rejected_chunk_count",
    "request_id",
    "requested_by",
    "required",
    "resolution",
    "retrieval_consumer",
    "retrieval_consumers",
    "retrieval_corpus_versions",
    "retrieval_source_count",
    "retrieved_chunk_count",
    "retryable",
    "routing_mode",
    "selected_agents",
    "source_count",
    "timeout_seconds",
}


def _write_workflow_log(
    *,
    trace_id: str,
    event_type: str,
    actor: str,
    task_id: str | None = None,
    parent_task_id: str | None = None,
    details: dict | None = None,
    level: int = logging.INFO,
) -> None:
    safe_details = {
        key: value
        for key, value in (details or {}).items()
        if key in SAFE_WORKFLOW_DETAIL_KEYS
    }
    for code_key in ("error_code", "reason_code"):
        if code_key not in safe_details:
            continue
        code_value = str(safe_details[code_key])
        if not (
            1 <= len(code_value) <= 128
            and all(
                character.isalnum() or character in "._-"
                for character in code_value
            )
        ):
            safe_details[code_key] = "UNSAFE_VALUE_REDACTED"
    logger.log(
        level,
        json.dumps(
            {
                "event_type": event_type,
                "trace_id": trace_id,
                "correlation_id": get_correlation_id(),
                "actor": actor,
                "task_id": task_id,
                "parent_task_id": parent_task_id,
                "details": safe_details,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    )


class OrchestratorState(TypedDict, total=False):
    request: CoachRequest
    trace_id: str
    executed_at: str
    sanitized_message: str
    guardrail_findings: list[str]
    selected_agents: list[AgentName]
    routing_rationale: list[str]
    tasks: dict[str, AgentTask]
    task_results: dict[str, AgentResult]
    agent_results: list[AgentResult]
    pending_dependencies: list[DependencyRequest]
    resolved_capabilities: dict[str, CapabilityResult]
    dependency_edges: list[DependencyEdge]
    dependency_resolutions: list[DependencyResolution]
    dependency_round: int
    tool_call_counts: dict[str, int]
    audit_events: list[AuditEvent]
    draft_answer: str
    compliance_result: AgentResult
    response: CoachResponse


class AgentOrchestrator:
    def __init__(
        self,
        *,
        config: Settings | None = None,
        gateway: ModelGateway | None = None,
        prompts: PromptCatalog | None = None,
        education_retriever: EducationRetriever | None = None,
        policy_retriever: PolicyRetriever | None = None,
        agents: Mapping[AgentName, BaseAgent] | None = None,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self.config = config or runtime_settings
        raw_gateway = gateway or create_model_gateway(self.config)
        self.gateway = (
            raw_gateway
            if isinstance(raw_gateway, TracingModelGateway)
            else TracingModelGateway(raw_gateway, self.config)
        )
        self.prompts = prompts or PromptCatalog(self.config.prompt_set_version)
        self.education_retriever = RequestScopedEducationRetriever(
            education_retriever or create_education_retriever(self.config)
        )
        self.policy_retriever = policy_retriever or create_policy_retriever(self.config)
        self.capability_registry = capability_registry or CapabilityRegistry()
        agent_args = (
            self.gateway,
            self.prompts,
            self.config.agent_temperature,
            self.config.model_max_tokens,
        )
        default_agents: dict[AgentName, BaseAgent] = {
            AgentName.SPENDING: SpendingAgent(*agent_args),
            AgentName.BUDGET: BudgetAgent(*agent_args),
            AgentName.GOAL_STRATEGY: GoalStrategyAgent(*agent_args),
            AgentName.INVESTMENT_EDUCATION: InvestmentEducationAgent(
                *agent_args,
                education_retriever=self.education_retriever,
            ),
        }
        self.agents = dict(agents) if agents is not None else default_agents
        self.compliance_agent = RiskComplianceAgent(
            self.gateway,
            self.prompts,
            self.config.compliance_temperature,
            self.config.model_max_tokens,
            self.policy_retriever,
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(OrchestratorState)
        workflow.add_node("guard_input", self._guard_input)
        workflow.add_node("route", self._route)
        workflow.add_node("initialize_tasks", self._initialize_tasks)
        workflow.add_node("run_ready_tasks", self._run_ready_tasks)
        workflow.add_node("resolve_dependencies", self._resolve_dependencies)
        workflow.add_node("synthesize", self._synthesize)
        workflow.add_node("review_compliance", self._review_compliance)
        workflow.add_node("finalize", self._finalize)
        workflow.add_edge(START, "guard_input")
        workflow.add_conditional_edges(
            "guard_input",
            lambda state: "blocked" if "response" in state else "continue",
            {"blocked": END, "continue": "route"},
        )
        workflow.add_edge("route", "initialize_tasks")
        workflow.add_edge("initialize_tasks", "run_ready_tasks")
        workflow.add_conditional_edges(
            "run_ready_tasks",
            self._stage_after_tasks,
            {"resolve": "resolve_dependencies", "complete": "synthesize"},
        )
        workflow.add_edge("resolve_dependencies", "run_ready_tasks")
        workflow.add_edge("synthesize", "review_compliance")
        workflow.add_edge("review_compliance", "finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    def _guard_input(self, state: OrchestratorState) -> OrchestratorState:
        request = state["request"]
        decision = inspect_prompt(request.message)
        event = self._event(
            state,
            "guardrail.evaluated",
            "orchestrator",
            details={"allowed": decision.allowed, "finding_count": len(decision.findings)},
        )
        events = [*state.get("audit_events", []), event]
        update: OrchestratorState = {
            "sanitized_message": decision.sanitized_text,
            "guardrail_findings": decision.findings,
            "audit_events": events,
        }
        if decision.allowed:
            return update

        response_language = education_response_language(decision.sanitized_text)
        blocked_result = AgentResult(
            agent=AgentName.RISK_COMPLIANCE,
            summary=(
                "请求已在协调流程入口被拦截。"
                if response_language == "Chinese"
                else "Request blocked at the orchestration boundary."
            ),
            rationale=[
                "请求触发了提示注入安全检查。"
                if response_language == "Chinese"
                else "Prompt-injection controls matched the request."
            ],
            confidence=1.0,
            blocked=True,
            policy_notes=decision.findings,
        )
        events.append(
            self._event(
                state,
                "workflow.completed",
                "orchestrator",
                details={"blocked": True, "reason_code": "BOUNDARY_GUARDRAIL"},
            )
        )
        update["audit_events"] = events
        update["response"] = CoachResponse(
            session_id=request.session_id,
            selected_agents=[],
            answer=(
                "此请求不符合安全要求，我无法处理。"
                if response_language == "Chinese"
                else "I cannot process that request because it conflicts with safety controls."
            ),
            agent_results=[blocked_result],
            disclaimers=[ADVISORY_DISCLAIMER],
            audit={
                "trace_id": state["trace_id"],
                "executed_at": state["executed_at"],
                "guardrail_findings": decision.findings,
                "prompt_set_version": self.prompts.version,
                "events": [item.model_dump(mode="json") for item in events],
            },
            blocked=True,
        )
        return update

    def _route(self, state: OrchestratorState) -> OrchestratorState:
        request = state["request"]
        response_language = education_response_language(state["sanitized_message"])
        requested_agents = list(
            dict.fromkeys(
                agent
                for agent in (request.requested_agents or [])
                if agent != AgentName.RISK_COMPLIANCE
            )
        )
        if requested_agents:
            decision = RouterDecision(
                selected_agents=requested_agents,
                rationale=[
                    "调用方已明确选择允许列表中的专业代理。"
                    if response_language == "Chinese"
                    else "The caller supplied an explicit allowlisted specialist selection."
                ],
            )
            routing_mode = "explicit"
            routing_actor = "orchestrator"
        else:
            payload = {
                "message": state["sanitized_message"],
                "requested_agents": None,
                "snapshot_features": {
                    "has_monthly_income": request.snapshot.monthly_income is not None,
                    "recurring_expense_count": len(request.snapshot.recurring_expenses),
                    "recent_transaction_count": len(request.snapshot.recent_transactions),
                    "goal_count": len(request.snapshot.goals),
                    "has_risk_tolerance": request.snapshot.risk_tolerance is not None,
                },
            }
            decision = generate_structured_response(
                self.gateway,
                response_type=RouterDecision,
                system_prompt=(
                    self.prompts.get("router")
                    + "\nWrite every rationale sentence in "
                    + response_language
                    + ". Keep machine agent names in selected_agents unchanged."
                ),
                user_prompt=json.dumps(payload, ensure_ascii=False),
                temperature=self.config.router_temperature,
                max_tokens=self.config.model_max_tokens,
            )
            routing_mode = "model"
            routing_actor = "router"
            if should_request_education_context(state["sanitized_message"]) and not any(
                agent in decision.selected_agents
                for agent in (AgentName.INVESTMENT_EDUCATION, AgentName.BUDGET, AgentName.GOAL_STRATEGY)
            ):
                decision.selected_agents.append(AgentName.INVESTMENT_EDUCATION)
                decision.rationale.append(
                    "已识别的教育主题需要由可访问经批准资料的专业代理处理。"
                    if response_language == "Chinese"
                    else "The recognized education topic requires a specialist with approved source access."
                )
        event = self._event(
            state,
            "routing.completed",
            routing_actor,
            details={
                "selected_agents": [agent.value for agent in decision.selected_agents],
                "routing_mode": routing_mode,
            },
        )
        return {
            "selected_agents": decision.selected_agents,
            "routing_rationale": decision.rationale,
            "audit_events": [*state.get("audit_events", []), event],
        }

    def _initialize_tasks(self, state: OrchestratorState) -> OrchestratorState:
        tasks: dict[str, AgentTask] = {}
        events = list(state.get("audit_events", []))
        for agent in state["selected_agents"]:
            task = self._create_task(state, agent)
            tasks[task.task_id] = task
            events.append(
                self._event(
                    state,
                    "task.created",
                    "orchestrator",
                    task_id=task.task_id,
                    details={"agent": agent.value, "requested_by": "router"},
                )
            )
        return {
            "tasks": tasks,
            "task_results": {},
            "agent_results": [],
            "pending_dependencies": [],
            "resolved_capabilities": {},
            "dependency_edges": [],
            "dependency_resolutions": [],
            "dependency_round": 0,
            "tool_call_counts": {},
            "audit_events": events,
        }

    def _run_ready_tasks(self, state: OrchestratorState) -> OrchestratorState:
        tasks = {task_id: task.model_copy(deep=True) for task_id, task in state["tasks"].items()}
        task_results = dict(state.get("task_results", {}))
        capabilities = dict(state.get("resolved_capabilities", {}))
        pending = list(state.get("pending_dependencies", []))
        events = list(state.get("audit_events", []))
        ready = [task for task in tasks.values() if task.status == AgentTaskStatus.READY]
        if not ready:
            return {
                "tasks": tasks,
                "task_results": task_results,
                "agent_results": self._ordered_results(
                    state["selected_agents"], tasks, task_results
                ),
                "pending_dependencies": pending,
                "resolved_capabilities": capabilities,
                "audit_events": events,
            }

        executor = ThreadPoolExecutor(
            max_workers=min(self.config.max_parallel_agents, len(ready)),
            thread_name_prefix="specialist",
        )
        futures = {}
        for task in ready:
            if task.attempt > self.config.max_task_attempts:
                raise ModelGatewayError("A specialist exceeded the allowed number of attempts.")
            try:
                agent = self.agents[task.agent]
            except KeyError as exc:
                raise ModelGatewayError("A selected specialist is not available.") from exc
            task.status = AgentTaskStatus.RUNNING
            events.append(
                self._event(
                    state,
                    "task.started",
                    task.agent.value,
                    task_id=task.task_id,
                    details={"attempt": task.attempt},
                )
            )
            context = copy_context()
            future = executor.submit(context.run, self._execute_task, task, agent)
            futures[future] = task.task_id

        done, not_done = wait(
            futures,
            timeout=self.config.agent_timeout_seconds,
        )
        outcomes = {futures[future]: future.result() for future in done}
        timed_out = {futures[future] for future in not_done}
        for future in not_done:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

        fatal_failure: tuple[str, str] | None = None
        for task in ready:
            if task.task_id in timed_out:
                task.status = AgentTaskStatus.TIMED_OUT
                events.append(
                    self._event(
                        state,
                        "task.timed_out",
                        task.agent.value,
                        task_id=task.task_id,
                        details={"timeout_seconds": self.config.agent_timeout_seconds},
                    )
                )
                if self._task_failure_is_required(state, task):
                    fatal_failure = ("AGENT_TIMEOUT", task.agent.value)
                continue

            outcome, final_attempt, retry_errors, duration_ms = outcomes[task.task_id]
            task.attempt = final_attempt
            for attempt, error_code in retry_errors:
                events.append(
                    self._event(
                        state,
                        "task.retry_scheduled",
                        task.agent.value,
                        task_id=task.task_id,
                        details={"attempt": attempt, "error_code": error_code},
                    )
                )

            if isinstance(outcome, CompletedInvocation):
                task.status = AgentTaskStatus.COMPLETED
                task_results[task.task_id] = outcome.result
                for capability in outcome.capabilities:
                    definition = self._validate_produced_capability(task, capability)
                    fingerprint = self._capability_input_fingerprint(state, definition)
                    capability.input_fingerprint = fingerprint
                    capabilities[self._capability_key(capability.capability, fingerprint)] = capability
                completion_details = {
                    "blocked": outcome.result.blocked,
                    "duration_ms": duration_ms,
                    "attempts": final_attempt,
                    "capabilities": [
                        item.capability.value for item in outcome.capabilities
                    ],
                }
                completion_details.update(
                    {
                        key: outcome.result.data[key]
                        for key in (
                            "retrieval_consumer",
                            "query_topics",
                            "evidence_status",
                            "corpus_version",
                            "retrieved_chunk_count",
                            "accepted_chunk_count",
                            "rejected_chunk_count",
                        )
                        if key in outcome.result.data
                    }
                )
                events.append(
                    self._event(
                        state,
                        "task.completed",
                        task.agent.value,
                        task_id=task.task_id,
                        details=completion_details,
                    )
                )
            elif isinstance(outcome, NeedsDependencyInvocation):
                task.status = AgentTaskStatus.WAITING_FOR_DEPENDENCY
                pending.extend(outcome.dependency_requests)
                for request in outcome.dependency_requests:
                    events.append(
                        self._event(
                            state,
                            "dependency.requested",
                            task.agent.value,
                            task_id=task.task_id,
                            details={
                                "request_id": request.request_id,
                                "capability": request.capability.value,
                                "reason_code": request.reason_code,
                                "required": request.required,
                            },
                        )
                    )
            elif isinstance(outcome, NeedsInputInvocation):
                task.status = AgentTaskStatus.NEEDS_INPUT
                task_results[task.task_id] = AgentResult(
                    agent=task.agent,
                    summary="Additional information is needed before this specialist can continue.",
                    rationale=[outcome.reason_code],
                    confidence=1.0,
                    data={"needs_input": True, "questions": outcome.questions},
                )
                events.append(
                    self._event(
                        state,
                        "task.needs_input",
                        task.agent.value,
                        task_id=task.task_id,
                        details={
                            "reason_code": outcome.reason_code,
                            "question_count": len(outcome.questions),
                        },
                    )
                )
            elif isinstance(outcome, FailedInvocation):
                task.status = AgentTaskStatus.FAILED
                events.append(
                    self._event(
                        state,
                        "task.failed",
                        task.agent.value,
                        task_id=task.task_id,
                        details={
                            "error_code": outcome.error_code,
                            "retryable": outcome.retryable,
                            "attempts": final_attempt,
                        },
                    )
                )
                if self._task_failure_is_required(state, task):
                    fatal_failure = (outcome.error_code, task.agent.value)
            else:
                raise ModelGatewayError("A specialist returned an unsupported result type.")

        if fatal_failure:
            error_code, component = fatal_failure
            raise ModelGatewayError(
                "A required specialist could not complete its assigned task.",
                code=error_code,
                component=component,
            )

        return {
            "tasks": tasks,
            "task_results": task_results,
            "agent_results": self._ordered_results(
                state["selected_agents"], tasks, task_results
            ),
            "pending_dependencies": pending,
            "resolved_capabilities": capabilities,
            "audit_events": events,
        }

    def _execute_task(self, task: AgentTask, agent: BaseAgent):
        started = perf_counter()
        retry_errors: list[tuple[int, str]] = []
        final_attempt = task.attempt
        while final_attempt <= self.config.max_task_attempts:
            try:
                outcome = agent.run_task(task.model_copy(update={"attempt": final_attempt}))
            except (ModelGatewayError, RetrievalError) as exc:
                error_code = getattr(
                    exc,
                    "code",
                    "RETRIEVAL_ERROR" if isinstance(exc, RetrievalError) else type(exc).__name__,
                )
                if final_attempt >= self.config.max_task_attempts:
                    outcome = FailedInvocation(
                        error_code=error_code,
                        retryable=True,
                        safe_message="The specialist could not complete after bounded retries.",
                    )
                    break
                retry_errors.append((final_attempt + 1, error_code))
                sleep(self.config.retry_backoff_seconds * (2 ** (final_attempt - 1)))
                final_attempt += 1
                continue
            if (
                isinstance(outcome, FailedInvocation)
                and outcome.retryable
                and final_attempt < self.config.max_task_attempts
            ):
                retry_errors.append((final_attempt + 1, outcome.error_code))
                sleep(self.config.retry_backoff_seconds * (2 ** (final_attempt - 1)))
                final_attempt += 1
                continue
            break
        return (
            outcome,
            final_attempt,
            retry_errors,
            round((perf_counter() - started) * 1000, 2),
        )

    @staticmethod
    def _task_failure_is_required(state: OrchestratorState, task: AgentTask) -> bool:
        if task.requested_by is None:
            return True
        provider_edges = [
            edge
            for edge in state.get("dependency_edges", [])
            if edge.provider_task_id == task.task_id
        ]
        requests = [
            request
            for request in state.get("pending_dependencies", [])
            if any(
                edge.requester_task_id == request.requester_task_id
                and edge.capability == request.capability
                for edge in provider_edges
            )
        ]
        return not requests or any(request.required for request in requests)

    def _stage_after_tasks(self, state: OrchestratorState) -> str:
        if state.get("pending_dependencies"):
            return "resolve"
        statuses = {task.status for task in state["tasks"].values()}
        if statuses.issubset(
            {
                AgentTaskStatus.COMPLETED,
                AgentTaskStatus.NEEDS_INPUT,
                AgentTaskStatus.CANCELLED,
            }
        ):
            return "complete"
        raise ModelGatewayError("The specialist scheduler reached an unresolved state.")

    def _resolve_dependencies(self, state: OrchestratorState) -> OrchestratorState:
        dependency_round = state.get("dependency_round", 0) + 1
        if dependency_round > self.config.max_dependency_rounds:
            raise ModelGatewayError("The workflow exceeded the dependency resolution limit.")

        tasks = {task_id: task.model_copy(deep=True) for task_id, task in state["tasks"].items()}
        selected_agents = list(state["selected_agents"])
        capabilities = dict(state.get("resolved_capabilities", {}))
        edges = list(state.get("dependency_edges", []))
        resolutions = list(state.get("dependency_resolutions", []))
        events = list(state.get("audit_events", []))
        tool_call_counts = dict(state.get("tool_call_counts", {}))
        unresolved: list[DependencyRequest] = []
        touched_requesters: set[str] = set()

        for request in state.get("pending_dependencies", []):
            touched_requesters.add(request.requester_task_id)
            requester_task = tasks.get(request.requester_task_id)
            if requester_task is None or requester_task.agent != request.requester:
                raise ModelGatewayError("A dependency request did not match its task.")

            try:
                definition = self.capability_registry.authorize(
                    request.requester,
                    request.capability,
                )
            except CapabilityRegistryError as exc:
                events.append(
                    self._event(
                        state,
                        "dependency.rejected",
                        "orchestrator",
                        task_id=request.requester_task_id,
                        details={
                            "request_id": request.request_id,
                            "capability": request.capability.value,
                            "reason_code": "CAPABILITY_NOT_AUTHORIZED",
                        },
                    )
                )
                raise ModelGatewayError("A dependency request was not authorized.") from exc

            fingerprint = self._capability_input_fingerprint(state, definition)
            request = request.model_copy(update={"input_fingerprint": fingerprint})
            capability_key = self._capability_key(request.capability, fingerprint)
            existing = (
                capabilities.get(capability_key)
                if definition.cacheable_within_run
                else None
            )
            if existing is not None:
                self._validate_dependency_fields(request, existing)
                requester_task.resolved_dependencies[request.capability] = existing
                reused_edge = DependencyEdge(
                    requester_task_id=request.requester_task_id,
                    provider_task_id=existing.provider_task_id,
                    capability=request.capability,
                )
                if reused_edge not in edges:
                    if self._creates_cycle(edges, reused_edge):
                        raise ModelGatewayError(
                            "A circular specialist dependency was detected."
                        )
                    edges.append(reused_edge)
                was_scheduled = any(
                    item.request_id == request.request_id and item.resolution == "scheduled"
                    for item in resolutions
                )
                resolution_type = "resolved" if was_scheduled else "reused"
                resolutions.append(
                    DependencyResolution(
                        request_id=request.request_id,
                        capability=request.capability,
                        requester_task_id=request.requester_task_id,
                        provider_task_id=existing.provider_task_id,
                        resolution=resolution_type,
                        input_fingerprint=fingerprint,
                    )
                )
                events.append(
                    self._event(
                        state,
                        "dependency.resolved",
                        "orchestrator",
                        task_id=request.requester_task_id,
                        parent_task_id=existing.provider_task_id,
                        details={
                            "request_id": request.request_id,
                            "capability": request.capability.value,
                            "resolution": resolution_type,
                            "input_fingerprint": fingerprint,
                        },
                    )
                )
                continue

            if definition.provider_type == CapabilityProviderType.TOOL:
                provider_task_id = f"tool:{definition.provider}:{fingerprint}"
                edge = DependencyEdge(
                    requester_task_id=request.requester_task_id,
                    provider_task_id=provider_task_id,
                    capability=request.capability,
                )
                if edge not in edges:
                    edges.append(edge)
                if (
                    request.capability != CapabilityName.EDUCATION_CONTEXT
                    or definition.provider != "education_retriever"
                ):
                    raise ModelGatewayError(
                        "A dynamic dependency did not resolve to an approved tool provider."
                    )
                provider_call_count = tool_call_counts.get(definition.provider, 0)
                if provider_call_count >= definition.maximum_calls_per_run:
                    if request.required:
                        raise ModelGatewayError(
                            "A capability exceeded its maximum provider calls per run."
                        )
                    warning = (
                        f"Optional capability {request.capability.value} was unavailable."
                    )
                    if warning not in requester_task.dependency_warnings:
                        requester_task.dependency_warnings.append(warning)
                    resolutions.append(
                        DependencyResolution(
                            request_id=request.request_id,
                            capability=request.capability,
                            requester_task_id=request.requester_task_id,
                            provider_task_id=provider_task_id,
                            resolution="rejected",
                            reason_code="OPTIONAL_TOOL_CALL_LIMIT",
                            input_fingerprint=fingerprint,
                        )
                    )
                    events.append(
                        self._event(
                            state,
                            "dependency.rejected",
                            "orchestrator",
                            task_id=request.requester_task_id,
                            parent_task_id=provider_task_id,
                            details={
                                "request_id": request.request_id,
                                "capability": request.capability.value,
                                "reason_code": "OPTIONAL_TOOL_CALL_LIMIT",
                            },
                        )
                    )
                    continue
                tool_call_counts[definition.provider] = provider_call_count + 1
                try:
                    validate_tool_permission(request.requester, definition.provider)
                    education_query, query_topics = build_minimal_education_query(
                        state["sanitized_message"]
                    )
                    data = build_education_context(
                        self.education_retriever,
                        education_query,
                        scope=(
                            "Approved investment education relevant to a budget or goal; "
                            "not product advice."
                        ),
                    )
                    apply_education_scope(data, state["sanitized_message"], query_topics)
                    capability_result = CapabilityResult(
                        capability=request.capability,
                        provider=definition.provider,
                        provider_task_id=provider_task_id,
                        data=data,
                        evidence_refs=[
                            (
                                f"{source['source_id']}@"
                                f"{source['document_version']}"
                            )
                            for source in data["sources"]
                        ],
                        warnings=(
                            []
                            if data["evidence_status"] == "grounded"
                            else [
                                "未检索到相关的经批准教育资料。"
                                if data["response_language"] == "Chinese"
                                else "No relevant approved Education source was retrieved."
                            ]
                        ),
                        input_fingerprint=fingerprint,
                    )
                    self._validate_dependency_fields(request, capability_result)
                    capabilities[capability_key] = capability_result
                    requester_task.resolved_dependencies[request.capability] = capability_result
                    resolutions.append(
                        DependencyResolution(
                            request_id=request.request_id,
                            capability=request.capability,
                            requester_task_id=request.requester_task_id,
                            provider_task_id=provider_task_id,
                            resolution="resolved",
                            input_fingerprint=fingerprint,
                        )
                    )
                    events.extend(
                        [
                            self._event(
                                state,
                                "capability.tool_completed",
                                definition.provider,
                                task_id=provider_task_id,
                                parent_task_id=request.requester_task_id,
                                details={
                                    "capability": request.capability.value,
                                    "requester": request.requester.value,
                                    "evidence_status": data["evidence_status"],
                                    "source_count": len(data["sources"]),
                                    "corpus_version": data["corpus_version"],
                                    "query_topics": list(query_topics),
                                },
                            ),
                            self._event(
                                state,
                                "dependency.resolved",
                                "orchestrator",
                                task_id=request.requester_task_id,
                                parent_task_id=provider_task_id,
                                details={
                                    "request_id": request.request_id,
                                    "capability": request.capability.value,
                                    "resolution": "resolved",
                                    "input_fingerprint": fingerprint,
                                },
                            ),
                        ]
                    )
                except (RetrievalError, ValueError) as exc:
                    if request.required:
                        raise ModelGatewayError(
                            "A required tool dependency was unavailable."
                        ) from exc
                    warning = (
                        f"Optional capability {request.capability.value} was unavailable."
                    )
                    if warning not in requester_task.dependency_warnings:
                        requester_task.dependency_warnings.append(warning)
                    resolutions.append(
                        DependencyResolution(
                            request_id=request.request_id,
                            capability=request.capability,
                            requester_task_id=request.requester_task_id,
                            provider_task_id=provider_task_id,
                            resolution="rejected",
                            reason_code="OPTIONAL_TOOL_UNAVAILABLE",
                            input_fingerprint=fingerprint,
                        )
                    )
                    events.append(
                        self._event(
                            state,
                            "dependency.rejected",
                            "orchestrator",
                            task_id=request.requester_task_id,
                            parent_task_id=provider_task_id,
                            details={
                                "request_id": request.request_id,
                                "capability": request.capability.value,
                                "reason_code": "OPTIONAL_TOOL_UNAVAILABLE",
                            },
                        )
                    )
                continue

            if definition.provider_type != CapabilityProviderType.AGENT:
                raise ModelGatewayError(
                    "A dynamic dependency did not resolve to a specialist provider."
                )

            try:
                provider_agent = AgentName(definition.provider)
            except ValueError as exc:
                raise ModelGatewayError("A capability provider is not a known specialist.") from exc

            provider_task = self._find_task_by_agent(tasks, provider_agent)
            if provider_task is None:
                provider_call_count = sum(
                    1 for task in tasks.values() if task.agent == provider_agent
                )
                if provider_call_count >= definition.maximum_calls_per_run:
                    raise ModelGatewayError(
                        "A capability exceeded its maximum provider calls per run."
                    )
                provider_task = self._create_task(
                    state,
                    provider_agent,
                    requested_by=request.requester,
                )
                tasks[provider_task.task_id] = provider_task
                if provider_agent not in selected_agents:
                    selected_agents.append(provider_agent)
                resolutions.append(
                    DependencyResolution(
                        request_id=request.request_id,
                        capability=request.capability,
                        requester_task_id=request.requester_task_id,
                        provider_task_id=provider_task.task_id,
                        resolution="scheduled",
                        input_fingerprint=fingerprint,
                    )
                )
                events.append(
                    self._event(
                        state,
                        "dependency.scheduled",
                        "orchestrator",
                        task_id=request.requester_task_id,
                        parent_task_id=provider_task.task_id,
                        details={
                            "request_id": request.request_id,
                            "capability": request.capability.value,
                            "provider": provider_agent.value,
                            "input_fingerprint": fingerprint,
                        },
                    )
                )

            edge = DependencyEdge(
                requester_task_id=request.requester_task_id,
                provider_task_id=provider_task.task_id,
                capability=request.capability,
            )
            if edge not in edges:
                if self._creates_cycle(edges, edge):
                    raise ModelGatewayError("A circular specialist dependency was detected.")
                edges.append(edge)

            if provider_task.status in {
                AgentTaskStatus.FAILED,
                AgentTaskStatus.BLOCKED_BY_DEPENDENCY,
                AgentTaskStatus.TIMED_OUT,
                AgentTaskStatus.CANCELLED,
            }:
                if request.required:
                    raise ModelGatewayError("A required dependency provider did not complete.")
                requester_task.dependency_warnings.append(
                    f"Optional capability {request.capability.value} was unavailable."
                )
                provider_task.status = AgentTaskStatus.CANCELLED
                resolutions.append(
                    DependencyResolution(
                        request_id=request.request_id,
                        capability=request.capability,
                        requester_task_id=request.requester_task_id,
                        provider_task_id=provider_task.task_id,
                        resolution="rejected",
                        reason_code="OPTIONAL_PROVIDER_UNAVAILABLE",
                        input_fingerprint=fingerprint,
                    )
                )
                events.append(
                    self._event(
                        state,
                        "dependency.rejected",
                        "orchestrator",
                        task_id=request.requester_task_id,
                        parent_task_id=provider_task.task_id,
                        details={
                            "request_id": request.request_id,
                            "capability": request.capability.value,
                            "reason_code": "OPTIONAL_PROVIDER_UNAVAILABLE",
                        },
                    )
                )
                continue
            if provider_task.status == AgentTaskStatus.COMPLETED:
                if request.required:
                    raise ModelGatewayError("A dependency provider did not produce its capability.")
                requester_task.dependency_warnings.append(
                    f"Optional capability {request.capability.value} returned no result."
                )
                resolutions.append(
                    DependencyResolution(
                        request_id=request.request_id,
                        capability=request.capability,
                        requester_task_id=request.requester_task_id,
                        provider_task_id=provider_task.task_id,
                        resolution="rejected",
                        reason_code="OPTIONAL_CAPABILITY_MISSING",
                        input_fingerprint=fingerprint,
                    )
                )
                continue
            unresolved.append(request)

        unresolved_requesters = {request.requester_task_id for request in unresolved}
        for requester_task_id in touched_requesters - unresolved_requesters:
            requester_task = tasks[requester_task_id]
            requester_task.status = AgentTaskStatus.READY
            requester_task.attempt += 1
            events.append(
                self._event(
                    state,
                    "task.resumed",
                    requester_task.agent.value,
                    task_id=requester_task_id,
                    details={"attempt": requester_task.attempt},
                )
            )

        return {
            "tasks": tasks,
            "selected_agents": selected_agents,
            "pending_dependencies": unresolved,
            "resolved_capabilities": capabilities,
            "dependency_edges": edges,
            "dependency_resolutions": resolutions,
            "dependency_round": dependency_round,
            "tool_call_counts": tool_call_counts,
            "audit_events": events,
        }

    def _synthesize(self, state: OrchestratorState) -> OrchestratorState:
        sources = self._collect_source_citations(state["agent_results"])
        events = [
            *state.get("audit_events", []),
            self._event(
                state,
                "synthesis.started",
                "synthesizer",
                details={"agent_result_count": len(state["agent_results"])},
            ),
        ]
        payload = {
            "message": state["sanitized_message"],
            "response_language": education_response_language(state["sanitized_message"]),
            "agent_results": [
                {
                    "agent": result.agent.value,
                    "summary": result.summary,
                    "rationale": result.rationale,
                    "confidence": result.confidence,
                    "source_ids": result.data.get("cited_source_ids", []),
                    "uncertainties": result.data.get("uncertainties", []),
                    "evidence_status": result.data.get("evidence_status"),
                    "unanswered_topics": result.data.get("unanswered_topics", []),
                    "question_intent": result.data.get("question_intent"),
                    "needs_input": result.data.get("needs_input", False),
                    "questions": result.data.get("questions", []),
                }
                for result in state["agent_results"]
            ],
            "sources": [source.model_dump() for source in sources],
        }
        synthesis_prompt = self.prompts.get("synthesizer")
        synthesis_prompt += citation_contract(sources)

        def validate_synthesis(synthesis: SynthesisDecision) -> SynthesisDecision:
            validate_citations(synthesis.answer, sources)
            return synthesis

        synthesis_prompt += (
            "\nRequired output language for THIS request: "
            + payload["response_language"]
            + ". Write the entire answer in this language. Reuse only the specialists' "
            "supported facts; do not add explanations, definitions or examples from memory."
        )
        if state["agent_results"] and all(
            result.data.get("needs_input") is True for result in state["agent_results"]
        ):
            questions = list(dict.fromkeys(
                question for result in state["agent_results"]
                for question in result.data.get("questions", [])
            ))
            synthesis = SynthesisDecision(answer="\n\n".join([
                state["agent_results"][0].summary, *questions,
            ]))
        elif (
            len(state["agent_results"]) == 1
            and state["agent_results"][0].agent == AgentName.INVESTMENT_EDUCATION
            and (
                self.prompts.version in {"v6", "v7"}
                or state["agent_results"][0].data.get("evidence_status") == "insufficient"
            )
        ):
            # Preserve the single specialist answer without a second model rewrite.
            # Citation validation and independent policy review still run below.
            synthesis = SynthesisDecision(answer=state["agent_results"][0].summary)
        else:
            synthesis = generate_structured_response(
                self.gateway,
                response_type=SynthesisDecision,
                system_prompt=synthesis_prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                temperature=self.config.agent_temperature,
                max_tokens=self.config.model_max_tokens,
                validate_response=validate_synthesis,
            )
        for result in state["agent_results"]:
            if result.data.get("evidence_status") in {"partial", "insufficient"}:
                gap = education_gap_message(result.data)
                if gap not in synthesis.answer:
                    synthesis.answer += f"\n\n{gap}"
        validate_citations(synthesis.answer, sources)
        events.append(
            self._event(
                state,
                "synthesis.completed",
                "synthesizer",
                details={"source_count": len(sources)},
            )
        )
        return {"draft_answer": synthesis.answer, "audit_events": events}

    def _review_compliance(self, state: OrchestratorState) -> OrchestratorState:
        events = [
            *state.get("audit_events", []),
            self._event(state, "compliance.started", AgentName.RISK_COMPLIANCE.value),
        ]
        result = self.compliance_agent.validate(
            state["request"],
            state["agent_results"],
            state["draft_answer"],
            routing_rationale=state["routing_rationale"],
        )
        events.append(
            self._event(
                state,
                "compliance.completed",
                AgentName.RISK_COMPLIANCE.value,
                details={
                    "blocked": result.blocked,
                    "policy_note_count": len(result.policy_notes),
                    "policy_source_count": len(result.data.get("policy_sources", [])),
                    "policy_corpus_version": result.data.get("policy_corpus_version"),
                },
            )
        )
        return {"compliance_result": result, "audit_events": events}

    def _finalize(self, state: OrchestratorState) -> OrchestratorState:
        compliance = state["compliance_result"]
        response_language = education_response_language(state["sanitized_message"])
        answer = state["draft_answer"]
        if compliance.blocked:
            answer = (
                "我无法提供该建议，但仍可提供一般金融教育信息。"
                if response_language == "Chinese"
                else "I cannot provide that recommendation. I can still offer general financial education."
            )
        sources = self._collect_source_citations(state["agent_results"])
        retrieval_evidence = self._collect_retrieval_evidence(state["agent_results"])
        retrieval_consumers = sorted(
            {
                str(result.data["retrieval_consumer"])
                for result in state["agent_results"]
                if result.data.get("retrieval_consumer")
            }
        )
        policy_evidence = self._collect_policy_evidence(compliance)
        corpus_versions = sorted(
            {
                str(result.data["corpus_version"])
                for result in state["agent_results"]
                if result.data.get("corpus_version")
            }
        )
        policy_corpus_versions = sorted(
            {
                str(version)
                for version in [
                    compliance.data.get("policy_corpus_version"),
                    *(item.get("corpus_version") for item in policy_evidence),
                ]
                if version
            }
        )
        events = [
            *state.get("audit_events", []),
            self._event(
                state,
                "workflow.completed",
                "orchestrator",
                details={
                    "blocked": compliance.blocked,
                    "retrieval_source_count": len(retrieval_evidence),
                    "retrieval_corpus_versions": corpus_versions,
                    "retrieval_consumers": retrieval_consumers,
                    "policy_source_count": len(policy_evidence),
                    "policy_corpus_versions": policy_corpus_versions,
                },
            ),
        ]
        public_results = state["agent_results"] + [compliance]
        if compliance.blocked:
            public_results = [
                withhold_agent_result(result, response_language=response_language)
                for result in public_results
            ]
            sources = []
        else:
            answer = render_citations(answer, sources)
            for text in state["routing_rationale"]:
                validate_citations(text, [])
            for result in public_results:
                result_sources = (
                    sources if result.agent == AgentName.RISK_COMPLIANCE
                    else self._collect_source_citations([result])
                ) + [
                    SourceCitation.model_validate(source)
                    for source in result.data.get("policy_sources", [])
                ]
                result.summary = render_citations(result.summary, result_sources)
                result.rationale = [
                    render_citations(text, result_sources) for text in result.rationale
                ]
                result.policy_notes = [
                    render_citations(text, result_sources) for text in result.policy_notes
                ]
                if "uncertainties" in result.data:
                    result.data["uncertainties"] = [
                        render_citations(text, result_sources)
                        for text in result.data["uncertainties"]
                    ]
        response = CoachResponse(
            session_id=state["request"].session_id,
            selected_agents=state["selected_agents"],
            answer=answer,
            agent_results=public_results,
            disclaimers=[ADVISORY_DISCLAIMER],
            sources=sources,
            audit={
                "trace_id": state["trace_id"],
                "executed_at": state["executed_at"],
                "guardrail_findings": state["guardrail_findings"],
                "agent_count": len(state["agent_results"]),
                "routing_rationale": (
                    [
                        "最终安全审查已拦截此回复。"
                        if response_language == "Chinese"
                        else "The final safety review blocked this response."
                    ]
                    if compliance.blocked else state["routing_rationale"]
                ),
                "model_provider": self.config.model_provider,
                "model_id": self.config.model_id,
                "prompt_set_version": self.prompts.version,
                "retrieval_corpus_versions": corpus_versions,
                "retrieval_sources": retrieval_evidence,
                "retrieval_consumers": retrieval_consumers,
                "policy_corpus_versions": policy_corpus_versions,
                "policy_sources": policy_evidence,
                "dependency_rounds": state.get("dependency_round", 0),
                "dependency_resolutions": [
                    item.model_dump(mode="json")
                    for item in state.get("dependency_resolutions", [])
                ],
                "dependency_edges": [
                    item.model_dump(mode="json")
                    for item in state.get("dependency_edges", [])
                ],
                "events": [item.model_dump(mode="json") for item in events],
            },
            blocked=compliance.blocked,
        )
        return {"response": response, "audit_events": events}

    def _create_task(
        self,
        state: OrchestratorState,
        agent: AgentName,
        *,
        requested_by: AgentName | None = None,
    ) -> AgentTask:
        snapshot = state["request"].snapshot
        if agent == AgentName.SPENDING:
            input_data = {
                "recent_transactions": [
                    item.model_dump(mode="json") for item in snapshot.recent_transactions
                ]
            }
        elif agent == AgentName.BUDGET:
            input_data = {
                "monthly_income": (
                    snapshot.monthly_income.model_dump(mode="json")
                    if snapshot.monthly_income is not None
                    else None
                ),
                "recurring_expenses": [
                    item.model_dump(mode="json") for item in snapshot.recurring_expenses
                ],
            }
        elif agent == AgentName.GOAL_STRATEGY:
            input_data = {
                "goals": [item.model_dump(mode="json") for item in snapshot.goals]
            }
        elif agent == AgentName.INVESTMENT_EDUCATION:
            input_data = {"risk_tolerance": snapshot.risk_tolerance}
        else:
            raise ModelGatewayError("The orchestrator cannot create that specialist task.")
        return AgentTask(
            agent=agent,
            sanitized_message=state["sanitized_message"],
            input_data=input_data,
            context_features={
                "has_monthly_income": snapshot.monthly_income is not None,
                "recurring_expense_count": len(snapshot.recurring_expenses),
                "recent_transaction_count": len(snapshot.recent_transactions),
                "goal_count": len(snapshot.goals),
                "has_risk_tolerance": snapshot.risk_tolerance is not None,
            },
            requested_by=requested_by,
        )

    @staticmethod
    def _find_task_by_agent(
        tasks: dict[str, AgentTask],
        agent: AgentName,
    ) -> AgentTask | None:
        return next((task for task in tasks.values() if task.agent == agent), None)

    @staticmethod
    def _ordered_results(
        selected_agents: list[AgentName],
        tasks: dict[str, AgentTask],
        task_results: dict[str, AgentResult],
    ) -> list[AgentResult]:
        results: list[AgentResult] = []
        for agent in selected_agents:
            task = next((item for item in tasks.values() if item.agent == agent), None)
            if task is not None and task.task_id in task_results:
                results.append(task_results[task.task_id])
        return results

    @staticmethod
    def _validate_dependency_fields(
        request: DependencyRequest,
        result: CapabilityResult,
    ) -> None:
        missing = [field for field in request.required_output_fields if field not in result.data]
        if missing:
            raise ModelGatewayError("A capability result omitted required output fields.")

    def _validate_produced_capability(
        self,
        task: AgentTask,
        result: CapabilityResult,
    ) -> CapabilityDefinition:
        try:
            definition = self.capability_registry.get(result.capability)
        except CapabilityRegistryError as exc:
            raise ModelGatewayError("A specialist produced an unknown capability.") from exc
        if result.provider_task_id != task.task_id or result.provider != task.agent.value:
            raise ModelGatewayError("A specialist capability had invalid provider metadata.")
        if (
            definition.provider_type == CapabilityProviderType.AGENT
            and definition.provider != task.agent.value
        ):
            raise ModelGatewayError("A specialist was not authorized to produce a capability.")
        if (
            definition.provider_type == CapabilityProviderType.TOOL
            and task.agent not in definition.allowed_requesters
        ):
            raise ModelGatewayError("A specialist was not authorized to expose a tool capability.")
        return definition

    @staticmethod
    def _capability_key(capability: CapabilityName, fingerprint: str) -> str:
        return f"{capability.value}:{fingerprint}"

    @staticmethod
    def _capability_input_fingerprint(
        state: OrchestratorState,
        definition: CapabilityDefinition,
    ) -> str:
        snapshot = state["request"].snapshot.model_dump(mode="json")
        values = {}
        for field in definition.required_inputs:
            if field == "sanitized_message":
                values[field] = state["sanitized_message"]
            elif field in snapshot:
                values[field] = snapshot[field]
            else:
                raise ModelGatewayError(
                    "A capability definition referenced an unavailable required input."
                )
        encoded = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _creates_cycle(existing: list[DependencyEdge], proposed: DependencyEdge) -> bool:
        if proposed.requester_task_id == proposed.provider_task_id:
            return True
        adjacency: dict[str, set[str]] = {}
        for edge in [*existing, proposed]:
            adjacency.setdefault(edge.requester_task_id, set()).add(edge.provider_task_id)

        target = proposed.requester_task_id
        pending = [proposed.provider_task_id]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(adjacency.get(current, set()))
        return False

    @staticmethod
    def _event(
        state: OrchestratorState,
        event_type: str,
        actor: str,
        *,
        task_id: str | None = None,
        parent_task_id: str | None = None,
        details: dict | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            trace_id=state["trace_id"],
            event_type=event_type,
            actor=actor,
            task_id=task_id,
            parent_task_id=parent_task_id,
            details=details or {},
        )
        _write_workflow_log(
            trace_id=event.trace_id,
            event_type=event.event_type,
            actor=event.actor,
            task_id=event.task_id,
            parent_task_id=event.parent_task_id,
            details=event.details,
        )
        return event

    @staticmethod
    def _collect_source_citations(results: list[AgentResult]) -> list[SourceCitation]:
        sources: list[SourceCitation] = []
        seen: set[str] = set()
        for result in results:
            cited_source_ids = {
                str(source_id)
                for source_id in result.data.get("cited_source_ids", [])
            }
            for item in result.data.get("sources", []):
                if not isinstance(item, dict):
                    continue
                source = SourceCitation.model_validate(item)
                if cited_source_ids and source.source_id not in cited_source_ids:
                    continue
                if source.source_id in seen:
                    continue
                seen.add(source.source_id)
                sources.append(source)
        return sources

    @staticmethod
    def _collect_retrieval_evidence(results: list[AgentResult]) -> list[dict[str, str]]:
        evidence = []
        seen = set()
        for result in results:
            for item in result.data.get("sources", []):
                source_id = str(item.get("source_id", ""))
                if not source_id or source_id in seen:
                    continue
                seen.add(source_id)
                evidence.append(
                    {
                        "source_id": source_id,
                        "document_version": str(item.get("document_version", "")),
                        "checksum": str(item.get("checksum", "")),
                        "corpus_version": str(item.get("corpus_version", "")),
                        "review_due_at": str(item.get("review_due_at", "")),
                    }
                )
        return evidence

    @staticmethod
    def _collect_policy_evidence(result: AgentResult) -> list[dict[str, str]]:
        evidence = []
        seen = set()
        for item in result.data.get("policy_sources", []):
            source_id = str(item.get("source_id", ""))
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            evidence.append(
                {
                    "source_id": source_id,
                    "title": str(item.get("title", "")),
                    "issuing_organization": str(
                        item.get("issuing_organization", "")
                    ),
                    "canonical_url": str(item.get("canonical_url", "")),
                    "published_at": str(item.get("published_at", "")),
                    "document_version": str(item.get("document_version", "")),
                    "checksum": str(item.get("checksum", "")),
                    "corpus_version": str(item.get("corpus_version", "")),
                    "review_due_at": str(item.get("review_due_at", "")),
                }
            )
        return evidence

    def handle(self, request: CoachRequest) -> CoachResponse:
        trace_id = str(uuid4())
        executed_at = datetime.now(UTC).isoformat()
        workflow_started = perf_counter()
        started_event = AuditEvent(
            trace_id=trace_id,
            event_type="workflow.started",
            actor="orchestrator",
            occurred_at=executed_at,
        )
        _write_workflow_log(
            trace_id=trace_id,
            event_type=started_event.event_type,
            actor=started_event.actor,
        )
        trace_token = self.gateway.bind_trace(trace_id)
        retrieval_token = self.education_retriever.begin_request()
        try:
            result = self.graph.invoke(
                {
                    "request": request,
                    "trace_id": trace_id,
                    "executed_at": executed_at,
                    "audit_events": [started_event],
                }
            )
            response = result["response"]
            model_calls = self.gateway.snapshot(trace_id)
            workflow_duration_ms = round(
                (perf_counter() - workflow_started) * 1000,
                2,
            )
            response.audit.update(
                {
                    "workflow_duration_ms": workflow_duration_ms,
                    "model_call_count": len(model_calls),
                    "model_input_tokens": sum(
                        int(call.get("input_tokens") or 0) for call in model_calls
                    ),
                    "model_output_tokens": sum(
                        int(call.get("output_tokens") or 0) for call in model_calls
                    ),
                    "model_calls": model_calls,
                }
            )
            _write_workflow_log(
                trace_id=trace_id,
                event_type="workflow.metrics",
                actor="orchestrator",
                details={
                    "duration_ms": workflow_duration_ms,
                    "model_call_count": len(model_calls),
                    "model_input_tokens": sum(
                        int(call.get("input_tokens") or 0) for call in model_calls
                    ),
                    "model_output_tokens": sum(
                        int(call.get("output_tokens") or 0) for call in model_calls
                    ),
                },
            )
            return response
        except Exception as exc:
            _write_workflow_log(
                trace_id=trace_id,
                event_type="workflow.failed",
                actor="orchestrator",
                details={
                    "duration_ms": round(
                        (perf_counter() - workflow_started) * 1000,
                        2,
                    ),
                    "error_code": getattr(exc, "code", "UNHANDLED_ERROR"),
                },
                level=logging.ERROR,
            )
            raise
        finally:
            self.education_retriever.end_request(retrieval_token)
            self.gateway.reset_trace(trace_token)
            self.gateway.clear(trace_id)
