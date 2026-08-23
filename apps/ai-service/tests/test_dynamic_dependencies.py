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
        message="Can I reach my emergency fund goal within twelve months?",
        requested_agents=requested_agents,
        snapshot={
            "monthly_income": {"amount": 5000},
            "recurring_expenses": [
                {
                    "description": "Rent",
                    "category": "housing",
                    "amount": {"amount": 1500},
                    "occurred_on": "2026-08-01",
                }
            ],
            "goals": [
                {
                    "name": "Emergency fund",
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
        "name": "Emergency fund",
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


def test_capability_registry_rejects_unauthorized_requester() -> None:
    registry = CapabilityRegistry()

    try:
        registry.authorize(AgentName.SPENDING, CapabilityName.MONTHLY_SAVINGS_CAPACITY)
    except CapabilityRegistryError as exc:
        assert "cannot request" in str(exc)
    else:
        raise AssertionError("Expected an unauthorized capability request to be rejected")


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
    assert set(task.input_data) == {"recent_transactions"}
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
