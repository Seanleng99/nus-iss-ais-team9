from concurrent.futures import wait as wait_for_completion

import pytest

import app.orchestrator as orchestrator_module
from app.core.config import Settings
from app.core.schemas import AgentName, AgentResult, CoachRequest, CompletedInvocation
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


class SimulatedStageGateway:
    """Account for provider latency without sleeping or making network calls."""

    def __init__(self):
        self.elapsed_seconds = 0
        self.calls = []

    def generate(self, *, prompt_role):
        self.calls.append(prompt_role)
        self.elapsed_seconds += 5
        return f"Completed {prompt_role}"


class MultiCallAgent:
    name = AgentName.SPENDING

    def __init__(self, gateway):
        self.gateway = gateway

    def run_task(self, task):
        stages = ["query_planning", "answerability", "writing", "repair", "assessment"]
        for stage in stages:
            self.gateway.generate(prompt_role=stage)
        return CompletedInvocation(
            result=AgentResult(
                agent=self.name,
                summary="The complete review is ready.",
                rationale=["All planning, evidence and writing stages completed."],
                confidence=1,
                data={"completed_stages": stages},
            )
        )


def test_workflow_deadline_stops_a_late_result_and_prevents_more_calls(monkeypatch):
    from app.core import deadline
    from app.models.gateway import TracingModelGateway
    clock = [0.0]
    monkeypatch.setattr(deadline, "perf_counter", lambda: clock[0])
    class LateGateway:
        def generate(self, **kwargs):
            clock[0] = 6.0
            return "{}"
    gateway = TracingModelGateway(LateGateway(), Settings(MODEL_PROVIDER="local_fixture"))
    token = deadline.workflow_deadline.set(5.0)
    try:
        for _ in range(2):
            with pytest.raises(ModelGatewayError) as failed:
                gateway.generate(system_prompt="PROMPT_ID: agent_spending", user_prompt="{}",
                                 temperature=0.2, max_tokens=100)
            assert failed.value.code == "WORKFLOW_TIMEOUT"
    finally:
        deadline.workflow_deadline.reset(token)


@pytest.mark.parametrize("deadline", [None, 20])
def test_multicall_specialist_finishes_under_default_but_exhausts_explicit_deadline(
    monkeypatch, deadline
):
    monkeypatch.delenv("AGENT_TIMEOUT_SECONDS", raising=False)
    stage_gateway = SimulatedStageGateway()

    def completed_with_simulated_provider_latency(futures, *, timeout):
        completed, unfinished = wait_for_completion(futures, timeout=2)
        assert not unfinished
        if stage_gateway.elapsed_seconds > timeout:
            raise TimeoutError
        yield from completed

    monkeypatch.setattr(orchestrator_module, "as_completed", completed_with_simulated_provider_latency)
    options = {"AGENT_TIMEOUT_SECONDS": deadline} if deadline is not None else {}
    coach = AgentOrchestrator(
        config=Settings(_env_file=None, MODEL_PROVIDER="local_fixture", **options),
        gateway=LocalFixtureModelGateway(),
        agents={AgentName.SPENDING: MultiCallAgent(stage_gateway)},
    )
    request = CoachRequest(
        user_id="u1",
        session_id="multicall-deadline",
        message="Summarize spending",
        requested_agents=["spending"],
    )
    if deadline is None:
        response = coach.handle(request)
        assert not response.blocked
        assert response.agent_results[0].data["completed_stages"] == stage_gateway.calls
        assert "task.timed_out" not in {event["event_type"] for event in response.audit["events"]}
    else:
        with pytest.raises(ModelGatewayError) as failed:
            coach.handle(request)
        assert failed.value.code == "AGENT_TIMEOUT"
    assert stage_gateway.calls == [
        "query_planning", "answerability", "writing", "repair", "assessment"
    ]
