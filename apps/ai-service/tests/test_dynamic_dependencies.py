import json
import time
from threading import Barrier

import pytest
from pydantic import ValidationError

from app.capabilities.registry import CapabilityRegistry, CapabilityRegistryError
from app.core.config import Settings
from app.core.schemas import (
    AgentName,
    AgentResult,
    CapabilityDefinition,
    CapabilityName,
    CapabilityProviderType,
    CapabilityResult,
    CoachRequest,
    CompletedInvocation,
    DependencyEdge,
    DependencyRequest,
    FailedInvocation,
    NeedsDependencyInvocation,
)
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class RecordingGateway(LocalFixtureModelGateway):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return super().generate(**kwargs)


def goal_request(*, requested_agents: list[str]) -> CoachRequest:
    return CoachRequest(
        user_id="u1",
        session_id="s1",
        message="Can I reach my home deposit goal within twelve months?",
        requested_agents=requested_agents,
        snapshot={
            "monthly_income": {"amount": 5000},
            "recurring_expenses": [
                {
                    "description": "Rent",
                    "category": "housing",
                    "amount": {"amount": 1500},
                    "occurred_on": "2026-08-01",
                    "obligation_id": "rent",
                    "recurrence": {"frequency": "monthly", "first_on": "2026-08-01", "next_due_on": "2026-09-01"},
                }
            ],
            "goals": [
                {
                    "name": "Home deposit",
                    "target_amount": {"amount": 12000},
                    "current_amount": {"amount": 0},
                    "target_months": 12,
                }
            ],
        },
    )


def test_goal_dynamically_schedules_budget_and_resumes() -> None:
    gateway = RecordingGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway,
    ).handle(goal_request(requested_agents=["goal_strategy"]))

    assert response.selected_agents == ["goal_strategy", "budget"]
    goal = next(result for result in response.agent_results if result.agent == "goal_strategy")
    assert goal.data["feasibility"][0] == {
        "name": "Home deposit",
        "monthly_required": 1000.0,
        "estimated_savings_capacity": 700.0,
        "monthly_shortfall": 300.0,
        "status": "shortfall",
    }
    assert "exceeds the estimated savings capacity" in response.answer

    budget_calls = [
        call
        for call in gateway.calls
        if call["system_prompt"].startswith("PROMPT_ID: agent_budget")
    ]
    assert len(budget_calls) == 1
    assert [item["resolution"] for item in response.audit["dependency_resolutions"]] == [
        "scheduled",
        "resolved",
    ]
    event_types = [event["event_type"] for event in response.audit["events"]]
    assert "dependency.requested" in event_types
    assert "dependency.scheduled" in event_types
    assert "dependency.resolved" in event_types
    assert "task.resumed" in event_types


def test_required_goal_dependency_cannot_be_skipped_by_model_planner() -> None:
    class AlwaysReadyPlannerGateway(RecordingGateway):
        def generate(self, **kwargs) -> str:
            if kwargs["system_prompt"].startswith("PROMPT_ID: dependency_planner"):
                self.calls.append(kwargs)
                return json.dumps(
                    {
                        "status": "ready",
                        "requests": [],
                        "questions": [],
                        "reason_code": None,
                    }
                )
            return super().generate(**kwargs)

    gateway = AlwaysReadyPlannerGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway,
    ).handle(goal_request(requested_agents=["goal_strategy"]))

    assert response.selected_agents == ["goal_strategy", "budget"]
    assert {
        item["capability"] for item in response.audit["dependency_resolutions"]
    } == {"monthly_savings_capacity"}
    assert not any(
        call["system_prompt"].startswith("PROMPT_ID: dependency_planner")
        for call in gateway.calls
    )


def test_preselected_budget_result_is_reused_without_duplicate_execution() -> None:
    gateway = RecordingGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway,
    ).handle(goal_request(requested_agents=["budget", "goal_strategy"]))

    assert response.selected_agents == ["budget", "goal_strategy"]
    assert response.audit["dependency_rounds"] == 1
    assert response.audit["dependency_resolutions"][0]["resolution"] == "reused"
    assert not any(
        event["event_type"] == "dependency.scheduled"
        for event in response.audit["events"]
    )
    assert sum(
        call["system_prompt"].startswith("PROMPT_ID: agent_budget")
        for call in gateway.calls
    ) == 1


def test_budget_skips_dependency_planner_when_there_is_nothing_to_decide() -> None:
    gateway = RecordingGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway,
    ).handle(
        CoachRequest(
            user_id="u1",
            session_id="no-op-preflight",
            message="Create a simple monthly budget",
            requested_agents=["budget"],
            snapshot={"monthly_income": {"amount": 4000}},
        )
    )

    assert response.blocked is False
    assert not any(
        call["system_prompt"].startswith("PROMPT_ID: dependency_planner")
        for call in gateway.calls
    )
    assert sum(
        call["system_prompt"].startswith("PROMPT_ID: agent_budget")
        for call in gateway.calls
    ) == 1


def test_model_cannot_escalate_optional_dependency_contract() -> None:
    class OverreachingGateway(LocalFixtureModelGateway):
        planner_called = False

        def generate(self, **kwargs) -> str:
            if kwargs["system_prompt"].startswith("PROMPT_ID: dependency_planner"):
                self.planner_called = True
                payload = json.loads(kwargs["user_prompt"])
                requested = dict(payload["allowed_requests"][0])
                requested.pop("selection_guidance")
                requested.update(
                    {
                        "reason_code": "MODEL_SELECTED_OVERRIDE",
                        "required_output_fields": ["unapproved_field"],
                        "required": True,
                    }
                )
                return json.dumps(
                    {
                        "status": "needs_dependency",
                        "requests": [requested],
                        "questions": [],
                        "reason_code": "MODEL_SELECTED_OVERRIDE",
                    }
                )
            return super().generate(**kwargs)

    gateway = OverreachingGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway,
    ).handle(
        CoachRequest(
            user_id="u1",
            session_id="contract-authority",
            message="Create a monthly budget using any useful context.",
            requested_agents=["budget"],
            snapshot={
                "monthly_income": {"amount": 4000},
                "recent_transactions": [
                    {
                        "description": "Groceries",
                        "category": "food",
                        "amount": {"amount": 200},
                        "occurred_on": "2026-08-02",
                    }
                ],
            },
        )
    )

    requested_event = next(
        event
        for event in response.audit["events"]
        if event["event_type"] == "dependency.requested"
    )
    assert requested_event["details"]["required"] is False
    assert requested_event["details"]["reason_code"] == (
        "BUDGET_CONTEXT_REQUIRES_SPENDING_TOTALS"
    )
    assert gateway.planner_called is True


def test_capability_registry_rejects_unauthorized_requester() -> None:
    registry = CapabilityRegistry()

    try:
        registry.authorize(AgentName.SPENDING, CapabilityName.MONTHLY_SAVINGS_CAPACITY)
    except CapabilityRegistryError as exc:
        assert "cannot request" in str(exc)
    else:
        raise AssertionError("Expected an unauthorized capability request to be rejected")

    with pytest.raises(CapabilityRegistryError, match="cannot request"):
        registry.authorize(AgentName.SPENDING, CapabilityName.EDUCATION_CONTEXT)


@pytest.mark.parametrize("requester", list(AgentName))
def test_education_context_authorizes_only_budget_and_goal_consumers(requester) -> None:
    registry = CapabilityRegistry()
    if requester in {AgentName.BUDGET, AgentName.GOAL_STRATEGY}:
        definition = registry.authorize(requester, CapabilityName.EDUCATION_CONTEXT)
        assert definition.provider == "education_retriever"
    else:
        with pytest.raises(CapabilityRegistryError, match="cannot request"):
            registry.authorize(requester, CapabilityName.EDUCATION_CONTEXT)


class RequestingAgent:
    def __init__(self, name: AgentName, capability: CapabilityName) -> None:
        self.name = name
        self.capability = capability

    def run_task(self, task):
        return NeedsDependencyInvocation(
            dependency_requests=[
                DependencyRequest(
                    requester_task_id=task.task_id,
                    requester=self.name,
                    capability=self.capability,
                    reason_code="TEST_DEPENDENCY",
                )
            ]
        )


def test_scheduler_rejects_circular_dynamic_dependencies() -> None:
    registry = CapabilityRegistry(
        [
            CapabilityDefinition(
                capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
                provider=AgentName.BUDGET.value,
                provider_type=CapabilityProviderType.AGENT,
                allowed_requesters={AgentName.GOAL_STRATEGY},
            ),
            CapabilityDefinition(
                capability=CapabilityName.GOAL_PROJECTION,
                provider=AgentName.GOAL_STRATEGY.value,
                provider_type=CapabilityProviderType.AGENT,
                allowed_requesters={AgentName.BUDGET},
            ),
        ]
    )
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
        agents={
            AgentName.GOAL_STRATEGY: RequestingAgent(
                AgentName.GOAL_STRATEGY,
                CapabilityName.MONTHLY_SAVINGS_CAPACITY,
            ),
            AgentName.BUDGET: RequestingAgent(
                AgentName.BUDGET,
                CapabilityName.GOAL_PROJECTION,
            ),
        },
        capability_registry=registry,
    )

    try:
        orchestrator.handle(goal_request(requested_agents=["goal_strategy"]))
    except ModelGatewayError as exc:
        assert "circular" in str(exc)
    else:
        raise AssertionError("Expected a circular dependency to fail closed")


class SpoofingAgent:
    name = AgentName.GOAL_STRATEGY

    def run_task(self, task):
        return CompletedInvocation(
            result=AgentResult(
                agent=self.name,
                summary="Invalid capability producer",
                rationale=["Test fixture"],
                confidence=1,
            ),
            capabilities=[
                CapabilityResult(
                    capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
                    provider=self.name.value,
                    provider_task_id=task.task_id,
                    data={"estimated_savings_capacity": 1},
                )
            ],
        )


def test_scheduler_rejects_capability_from_wrong_provider() -> None:
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
        agents={AgentName.GOAL_STRATEGY: SpoofingAgent()},
    )

    try:
        orchestrator.handle(goal_request(requested_agents=["goal_strategy"]))
    except ModelGatewayError as exc:
        assert "not authorized to produce" in str(exc)
    else:
        raise AssertionError("Expected a spoofed capability provider to fail closed")


class RecordingCompletedAgent:
    name = AgentName.SPENDING

    def __init__(self) -> None:
        self.tasks = []

    def run_task(self, task):
        self.tasks.append(task)
        return CompletedInvocation(
            result=AgentResult(
                agent=self.name,
                summary="Recorded role-scoped task",
                rationale=["Test fixture"],
                confidence=1,
            )
        )


def test_orchestrator_passes_only_role_scoped_input_to_specialist() -> None:
    spending = RecordingCompletedAgent()
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
        agents={AgentName.SPENDING: spending},
    )
    request = CoachRequest(
        user_id="private-user-id",
        session_id="private-session-id",
        message="Summarize spending for person@example.com",
        requested_agents=["spending"],
        snapshot={
            "monthly_income": {"amount": 5000},
            "recent_transactions": [
                {
                    "description": "Train",
                    "category": "transport",
                    "amount": {"amount": 20},
                    "occurred_on": "2026-08-01",
                }
            ],
            "goals": [
                {
                    "name": "Private goal",
                    "target_amount": {"amount": 1000},
                    "target_months": 10,
                }
            ],
        },
    )

    orchestrator.handle(request)

    assert len(spending.tasks) == 1
    task = spending.tasks[0]
    assert set(task.input_data) == {"recent_transactions", "historical_transactions", "period_start", "transaction_context"}
    assert task.sanitized_message == "Summarize spending for [REDACTED_EMAIL]"
    assert "private-user-id" not in task.model_dump_json()
    assert "private-session-id" not in task.model_dump_json()


def test_agent_task_contract_rejects_fields_outside_role_scope() -> None:
    from app.core.schemas import AgentTask

    try:
        AgentTask(
            agent=AgentName.SPENDING,
            sanitized_message="Summarize spending",
            input_data={"recent_transactions": [], "monthly_income": {"amount": 5000}},
        )
    except ValidationError as exc:
        assert "outside its role scope" in str(exc)
    else:
        raise AssertionError("Expected role-scope validation to reject monthly income")


def test_cycle_detector_accepts_chain_and_rejects_back_edge() -> None:
    first = DependencyEdge(
        requester_task_id="goal",
        provider_task_id="budget",
        capability=CapabilityName.MONTHLY_SAVINGS_CAPACITY,
    )
    back_edge = DependencyEdge(
        requester_task_id="budget",
        provider_task_id="goal",
        capability=CapabilityName.GOAL_PROJECTION,
    )

    assert AgentOrchestrator._creates_cycle([], first) is False
    assert AgentOrchestrator._creates_cycle([first], back_edge) is True


def test_goal_budget_spending_dependency_chain_fans_in() -> None:
    request = goal_request(requested_agents=["goal_strategy"])
    payload = request.model_dump(mode="json")
    payload["message"] = (
        "Use my recent spending to assess whether I can reach my home deposit goal."
    )
    payload["snapshot"]["recent_transactions"] = [
        {
            "description": "Groceries",
            "category": "food",
            "amount": {"amount": 300},
            "occurred_on": "2026-08-02",
        }
    ]
    request = CoachRequest.model_validate(payload)

    gateway = RecordingGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway,
    ).handle(request)

    assert response.selected_agents == ["goal_strategy", "budget", "spending"]
    budget = next(result for result in response.agent_results if result.agent == "budget")
    assert budget.data["spending_context"]["category_totals"] == {"food": 300.0}
    goal = next(result for result in response.agent_results if result.agent == "goal_strategy")
    assert goal.data["feasibility"][0]["status"] == "shortfall"
    resolutions = response.audit["dependency_resolutions"]
    assert {item["capability"] for item in resolutions} == {
        "monthly_savings_capacity",
        "transaction_category_totals",
    }
    assert all(item["input_fingerprint"] for item in resolutions)
    assert any(
        call["system_prompt"].startswith("PROMPT_ID: dependency_planner")
        for call in gateway.calls
    )


def test_missing_budget_input_returns_typed_needs_input_result() -> None:
    gateway = RecordingGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway,
    ).handle(
        CoachRequest(
            user_id="u1",
            session_id="needs-input",
            message="Create a budget",
            requested_agents=["budget"],
        )
    )

    budget = next(result for result in response.agent_results if result.agent == "budget")
    assert budget.data["needs_input"] is True
    assert budget.data["questions"] == [
        "What is your monthly take-home income in SGD, and what confirmed monthly expenses or commitments should this assessment include?"
    ]
    assert "task.needs_input" in {
        event["event_type"] for event in response.audit["events"]
    }
    assert not any(
        call["system_prompt"].startswith("PROMPT_ID: dependency_planner")
        for call in gateway.calls
    )


class ConcurrentCompletedAgent:
    def __init__(self, name: AgentName, rendezvous: Barrier) -> None:
        self.name = name
        self.rendezvous = rendezvous

    def run_task(self, task):
        # Both specialists must be running before either is allowed to finish.
        self.rendezvous.wait(timeout=5)
        return CompletedInvocation(
            result=AgentResult(
                agent=self.name,
                summary=f"{self.name.value} completed",
                rationale=["parallel test"],
                confidence=1,
            )
        )


def test_independent_ready_agents_execute_concurrently() -> None:
    rendezvous = Barrier(2)
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture", MAX_PARALLEL_AGENTS=2),
        gateway=LocalFixtureModelGateway(),
        agents={
            AgentName.SPENDING: ConcurrentCompletedAgent(AgentName.SPENDING, rendezvous),
            AgentName.INVESTMENT_EDUCATION: ConcurrentCompletedAgent(
                AgentName.INVESTMENT_EDUCATION,
                rendezvous,
            ),
        },
    )
    response = orchestrator.handle(
        CoachRequest(
            user_id="u1",
            session_id="parallel",
            message="Summarize spending and explain investment risk",
            requested_agents=["spending", "investment_education"],
        )
    )

    assert {AgentName.SPENDING, AgentName.INVESTMENT_EDUCATION} <= {
        result.agent for result in response.agent_results
    }


class RetryOnceAgent:
    name = AgentName.SPENDING

    def __init__(self) -> None:
        self.calls = 0

    def run_task(self, task):
        self.calls += 1
        if self.calls == 1:
            raise ModelGatewayError("transient")
        return CompletedInvocation(
            result=AgentResult(
                agent=self.name,
                summary="Recovered",
                rationale=["bounded retry"],
                confidence=1,
            )
        )


def test_retryable_specialist_failure_is_retried_with_trace_event() -> None:
    agent = RetryOnceAgent()
    response = AgentOrchestrator(
        config=Settings(
            MODEL_PROVIDER="local_fixture",
            MAX_TASK_ATTEMPTS=2,
            RETRY_BACKOFF_SECONDS=0,
        ),
        gateway=LocalFixtureModelGateway(),
        agents={AgentName.SPENDING: agent},
    ).handle(
        CoachRequest(
            user_id="u1",
            session_id="retry",
            message="Summarize spending",
            requested_agents=["spending"],
        )
    )

    assert agent.calls == 2
    assert "task.retry_scheduled" in {
        event["event_type"] for event in response.audit["events"]
    }


class SlowAgent:
    name = AgentName.SPENDING

    def run_task(self, task):
        time.sleep(0.1)
        return CompletedInvocation(
            result=AgentResult(
                agent=self.name,
                summary="Too late",
                rationale=["timeout test"],
                confidence=1,
            )
        )


def test_required_specialist_timeout_fails_closed() -> None:
    orchestrator = AgentOrchestrator(
        config=Settings(
            MODEL_PROVIDER="local_fixture",
            AGENT_TIMEOUT_SECONDS=0.01,
            MAX_TASK_ATTEMPTS=1,
        ),
        gateway=LocalFixtureModelGateway(),
        agents={AgentName.SPENDING: SlowAgent()},
    )

    try:
        orchestrator.handle(
            CoachRequest(
                user_id="u1",
                session_id="timeout",
                message="Summarize spending",
                requested_agents=["spending"],
            )
        )
    except ModelGatewayError as exc:
        assert "required specialist" in str(exc)
    else:
        raise AssertionError("Expected a required specialist timeout to fail closed")


class UnavailableSpendingAgent:
    name = AgentName.SPENDING

    def run_task(self, task):
        return FailedInvocation(
            error_code="OPTIONAL_CONTEXT_UNAVAILABLE",
            retryable=False,
            safe_message="Optional spending context is unavailable.",
        )


def test_optional_dependency_failure_allows_budget_and_goal_to_continue() -> None:
    request = goal_request(requested_agents=["goal_strategy"])
    payload = request.model_dump(mode="json")
    payload["message"] = "Use my spending patterns to assess whether I can reach my home deposit goal."
    payload["snapshot"]["recent_transactions"] = [
        {
            "description": "Groceries",
            "category": "food",
            "amount": {"amount": 300},
            "occurred_on": "2026-08-02",
        }
    ]
    request = CoachRequest.model_validate(payload)
    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
    )
    orchestrator.agents[AgentName.SPENDING] = UnavailableSpendingAgent()

    response = orchestrator.handle(request)

    budget = next(result for result in response.agent_results if result.agent == "budget")
    assert budget.data["dependency_warnings"] == [
        "Optional capability transaction_category_totals was unavailable."
    ]
    assert response.blocked is False
    assert any(
        item["resolution"] == "rejected"
        and item["reason_code"] == "OPTIONAL_PROVIDER_UNAVAILABLE"
        for item in response.audit["dependency_resolutions"]
    )
