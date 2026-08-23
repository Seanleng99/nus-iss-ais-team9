import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.base import BaseAgent
from app.agents.budget import BudgetAgent
from app.agents.goal_strategy import GoalStrategyAgent
from app.agents.investment_education import InvestmentEducationAgent
from app.agents.risk_compliance import RiskComplianceAgent
from app.agents.spending import SpendingAgent
from app.capabilities.registry import CapabilityRegistry, CapabilityRegistryError
from app.core.config import Settings
from app.core.config import settings as runtime_settings
from app.core.guardrails import ADVISORY_DISCLAIMER, inspect_prompt
from app.core.observability import get_correlation_id
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    AgentTaskStatus,
    AuditEvent,
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
    RouterDecision,
    SourceCitation,
    SynthesisDecision,
)
from app.models.gateway import ModelGateway, ModelGatewayError, create_model_gateway
from app.models.structured import parse_structured_response
from app.rag.retriever import EducationRetriever, create_education_retriever


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
    resolved_capabilities: dict[CapabilityName, CapabilityResult]
    dependency_edges: list[DependencyEdge]
    dependency_resolutions: list[DependencyResolution]
    dependency_round: int
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
        agents: Mapping[AgentName, BaseAgent] | None = None,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self.config = config or runtime_settings
        self.gateway = gateway or create_model_gateway(self.config)
        self.prompts = prompts or PromptCatalog(self.config.prompt_set_version)
        self.education_retriever = education_retriever or create_education_retriever(self.config)
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

        blocked_result = AgentResult(
            agent=AgentName.RISK_COMPLIANCE,
            summary="Request blocked at the orchestration boundary.",
            rationale=["Prompt-injection controls matched the request."],
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
            answer="I cannot process that request because it conflicts with safety controls.",
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
        requested_agents = [
            agent.value
            for agent in (request.requested_agents or [])
            if agent != AgentName.RISK_COMPLIANCE
        ]
        payload = {
            "message": state["sanitized_message"],
            "requested_agents": requested_agents or None,
            "snapshot_features": {
                "has_monthly_income": request.snapshot.monthly_income is not None,
                "recurring_expense_count": len(request.snapshot.recurring_expenses),
                "recent_transaction_count": len(request.snapshot.recent_transactions),
                "goal_count": len(request.snapshot.goals),
                "has_risk_tolerance": request.snapshot.risk_tolerance is not None,
            },
        }
        raw = self.gateway.generate(
            system_prompt=self.prompts.get("router"),
            user_prompt=json.dumps(payload, ensure_ascii=True),
            temperature=self.config.router_temperature,
            max_tokens=self.config.model_max_tokens,
        )
        decision = parse_structured_response(raw, RouterDecision)
        event = self._event(
            state,
            "routing.completed",
            "router",
            details={"selected_agents": [agent.value for agent in decision.selected_agents]},
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
            "audit_events": events,
        }

    def _run_ready_tasks(self, state: OrchestratorState) -> OrchestratorState:
        tasks = {task_id: task.model_copy(deep=True) for task_id, task in state["tasks"].items()}
        task_results = dict(state.get("task_results", {}))
        capabilities = dict(state.get("resolved_capabilities", {}))
        pending = list(state.get("pending_dependencies", []))
        events = list(state.get("audit_events", []))

        for task in tasks.values():
            if task.status != AgentTaskStatus.READY:
                continue
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
            outcome = agent.run_task(task)

            if isinstance(outcome, CompletedInvocation):
                task.status = AgentTaskStatus.COMPLETED
                task_results[task.task_id] = outcome.result
                for capability in outcome.capabilities:
                    self._validate_produced_capability(task, capability)
                    capabilities[capability.capability] = capability
                events.append(
                    self._event(
                        state,
                        "task.completed",
                        task.agent.value,
                        task_id=task.task_id,
                        details={
                            "blocked": outcome.result.blocked,
                            "capabilities": [
                                item.capability.value for item in outcome.capabilities
                            ],
                        },
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
                        },
                    )
                )
                raise ModelGatewayError("A specialist could not complete its assigned task.")
            else:
                raise ModelGatewayError("A specialist returned an unsupported result type.")

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

    def _stage_after_tasks(self, state: OrchestratorState) -> str:
        if state.get("pending_dependencies"):
            return "resolve"
        statuses = {task.status for task in state["tasks"].values()}
        if statuses.issubset({AgentTaskStatus.COMPLETED}):
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

            existing = capabilities.get(request.capability)
            if existing is not None:
                self._validate_dependency_fields(request, existing)
                requester_task.resolved_dependencies[request.capability] = existing
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
                raise ModelGatewayError("A required dependency provider did not complete.")
            if provider_task.status == AgentTaskStatus.COMPLETED:
                raise ModelGatewayError("A dependency provider did not produce its capability.")
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
            "agent_results": [
                {
                    "agent": result.agent.value,
                    "summary": result.summary,
                    "rationale": result.rationale,
                    "confidence": result.confidence,
                }
                for result in state["agent_results"]
            ],
            "sources": [source.model_dump() for source in sources],
        }
        raw = self.gateway.generate(
            system_prompt=self.prompts.get("synthesizer"),
            user_prompt=json.dumps(payload, ensure_ascii=True),
            temperature=self.config.agent_temperature,
            max_tokens=self.config.model_max_tokens,
        )
        synthesis = parse_structured_response(raw, SynthesisDecision)
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
        )
        events.append(
            self._event(
                state,
                "compliance.completed",
                AgentName.RISK_COMPLIANCE.value,
                details={"blocked": result.blocked, "policy_note_count": len(result.policy_notes)},
            )
        )
        return {"compliance_result": result, "audit_events": events}

    def _finalize(self, state: OrchestratorState) -> OrchestratorState:
        compliance = state["compliance_result"]
        answer = state["draft_answer"]
        if compliance.blocked:
            answer = (
                "I cannot provide that recommendation. I can still offer general financial education."
            )
        events = [
            *state.get("audit_events", []),
            self._event(
                state,
                "workflow.completed",
                "orchestrator",
                details={"blocked": compliance.blocked},
            ),
        ]
        response = CoachResponse(
            session_id=state["request"].session_id,
            selected_agents=state["selected_agents"],
            answer=answer,
            agent_results=state["agent_results"] + [compliance],
            disclaimers=[ADVISORY_DISCLAIMER],
            sources=self._collect_source_citations(state["agent_results"]),
            audit={
                "trace_id": state["trace_id"],
                "executed_at": state["executed_at"],
                "guardrail_findings": state["guardrail_findings"],
                "agent_count": len(state["agent_results"]),
                "routing_rationale": state["routing_rationale"],
                "model_provider": self.config.model_provider,
                "model_id": self.config.model_id,
                "prompt_set_version": self.prompts.version,
                "dependency_rounds": state.get("dependency_round", 0),
                "dependency_resolutions": [
                    item.model_dump(mode="json")
                    for item in state.get("dependency_resolutions", [])
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
    ) -> None:
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
        return AuditEvent(
            trace_id=state["trace_id"],
            event_type=event_type,
            actor=actor,
            task_id=task_id,
            parent_task_id=parent_task_id,
            details=details or {},
        )

    @staticmethod
    def _collect_source_citations(results: list[AgentResult]) -> list[SourceCitation]:
        sources: list[SourceCitation] = []
        seen: set[str] = set()
        for result in results:
            for item in result.data.get("sources", []):
                if not isinstance(item, dict):
                    continue
                source = SourceCitation.model_validate(item)
                if source.source_id in seen:
                    continue
                seen.add(source.source_id)
                sources.append(source)
        return sources

    def handle(self, request: CoachRequest) -> CoachResponse:
        trace_id = get_correlation_id() or str(uuid4())
        executed_at = datetime.now(UTC).isoformat()
        started_event = AuditEvent(
            trace_id=trace_id,
            event_type="workflow.started",
            actor="orchestrator",
            occurred_at=executed_at,
        )
        result = self.graph.invoke(
            {
                "request": request,
                "trace_id": trace_id,
                "executed_at": executed_at,
                "audit_events": [started_event],
            }
        )
        return result["response"]
