import json
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.budget import BudgetAgent
from app.agents.goal_strategy import GoalStrategyAgent
from app.agents.investment_education import InvestmentEducationAgent
from app.agents.risk_compliance import RiskComplianceAgent
from app.agents.spending import SpendingAgent
from app.core.config import Settings
from app.core.config import settings as runtime_settings
from app.core.guardrails import ADVISORY_DISCLAIMER, inspect_prompt
from app.core.observability import get_correlation_id
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentResult,
    CoachRequest,
    CoachResponse,
    RouterDecision,
    SynthesisDecision,
)
from app.models.gateway import ModelGateway, create_model_gateway
from app.models.structured import parse_structured_response


class OrchestratorState(TypedDict, total=False):
    request: CoachRequest
    trace_id: str
    executed_at: str
    sanitized_message: str
    guardrail_findings: list[str]
    selected_agents: list[AgentName]
    routing_rationale: list[str]
    agent_results: list[AgentResult]
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
    ) -> None:
        self.config = config or runtime_settings
        self.gateway = gateway or create_model_gateway(self.config)
        self.prompts = prompts or PromptCatalog(self.config.prompt_set_version)
        agent_args = (
            self.gateway,
            self.prompts,
            self.config.agent_temperature,
            self.config.model_max_tokens,
        )
        self.agents = {
            AgentName.SPENDING: SpendingAgent(*agent_args),
            AgentName.BUDGET: BudgetAgent(*agent_args),
            AgentName.GOAL_STRATEGY: GoalStrategyAgent(*agent_args),
            AgentName.INVESTMENT_EDUCATION: InvestmentEducationAgent(*agent_args),
        }
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
        workflow.add_node("run_specialists", self._run_specialists)
        workflow.add_node("synthesize", self._synthesize)
        workflow.add_node("review_compliance", self._review_compliance)
        workflow.add_node("finalize", self._finalize)
        workflow.add_edge(START, "guard_input")
        workflow.add_conditional_edges(
            "guard_input",
            lambda state: "blocked" if "response" in state else "continue",
            {"blocked": END, "continue": "route"},
        )
        workflow.add_edge("route", "run_specialists")
        workflow.add_edge("run_specialists", "synthesize")
        workflow.add_edge("synthesize", "review_compliance")
        workflow.add_edge("review_compliance", "finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    def _guard_input(self, state: OrchestratorState) -> OrchestratorState:
        request = state["request"]
        decision = inspect_prompt(request.message)
        update: OrchestratorState = {
            "sanitized_message": decision.sanitized_text,
            "guardrail_findings": decision.findings,
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
        return {
            "selected_agents": decision.selected_agents,
            "routing_rationale": decision.rationale,
        }

    def _run_specialists(self, state: OrchestratorState) -> OrchestratorState:
        request = state["request"]
        results = [self.agents[agent].run(request) for agent in state["selected_agents"]]
        return {"agent_results": results}

    def _synthesize(self, state: OrchestratorState) -> OrchestratorState:
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
        }
        raw = self.gateway.generate(
            system_prompt=self.prompts.get("synthesizer"),
            user_prompt=json.dumps(payload, ensure_ascii=True),
            temperature=self.config.agent_temperature,
            max_tokens=self.config.model_max_tokens,
        )
        synthesis = parse_structured_response(raw, SynthesisDecision)
        return {"draft_answer": synthesis.answer}

    def _review_compliance(self, state: OrchestratorState) -> OrchestratorState:
        result = self.compliance_agent.validate(
            state["request"],
            state["agent_results"],
            state["draft_answer"],
        )
        return {"compliance_result": result}

    def _finalize(self, state: OrchestratorState) -> OrchestratorState:
        compliance = state["compliance_result"]
        answer = state["draft_answer"]
        if compliance.blocked:
            answer = (
                "I cannot provide that recommendation. I can still offer general financial education."
            )
        response = CoachResponse(
            session_id=state["request"].session_id,
            selected_agents=state["selected_agents"],
            answer=answer,
            agent_results=state["agent_results"] + [compliance],
            disclaimers=[ADVISORY_DISCLAIMER],
            audit={
                "trace_id": state["trace_id"],
                "executed_at": state["executed_at"],
                "guardrail_findings": state["guardrail_findings"],
                "agent_count": len(state["agent_results"]),
                "routing_rationale": state["routing_rationale"],
                "model_provider": self.config.model_provider,
                "model_id": self.config.model_id,
                "prompt_set_version": self.prompts.version,
            },
            blocked=compliance.blocked,
        )
        return {"response": response}

    def handle(self, request: CoachRequest) -> CoachResponse:
        result = self.graph.invoke(
            {
                "request": request,
                "trace_id": get_correlation_id() or str(uuid4()),
                "executed_at": datetime.now(UTC).isoformat(),
            }
        )
        return result["response"]
