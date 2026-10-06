import json
from threading import Event
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.run_trace import event_sink, workflow_id
from app.core.schemas import (
    AgentName,
    AgentNarrative,
    AgentResult,
    AgentTask,
    CoachRequest,
    CompletedInvocation,
)
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError, TracingModelGateway
from app.models.structured import generate_structured_response
from app.orchestrator import AgentOrchestrator


def test_correction_links_generation_validation_and_acceptance_without_content():
    class InvalidThenValid:
        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            return (
                "PRIVATE invalid"
                if self.calls == 1
                else json.dumps(
                    {
                        "summary": "PRIVATE approved",
                        "rationale": ["PRIVATE reason"],
                        "confidence": 1,
                    }
                )
            )

    trace_id = str(uuid4())
    events = []
    flow = workflow_id.set(trace_id)
    sink = event_sink.set(events.append)
    gateway = TracingModelGateway(InvalidThenValid(), Settings(MODEL_PROVIDER="local_fixture"))
    token = gateway.bind_trace(trace_id)
    try:
        generate_structured_response(
            gateway,
            response_type=AgentNarrative,
            system_prompt="PROMPT_ID: agent_budget",
            user_prompt="PRIVATE",
            temperature=0,
            max_tokens=500,
        )
    finally:
        gateway.reset_trace(token)
        gateway.clear(trace_id)
        event_sink.reset(sink)
        workflow_id.reset(flow)
    starts = [e for e in events if e["event_type"] == "model.generation.started"]
    first, second = [e["details"]["call_id"] for e in starts]
    assert any(
        e["event_type"] == "model.contract.rejected" and e["details"]["call_id"] == first
        for e in events
    )
    assert any(
        e["event_type"] == "model.decision.rejected" and e["details"]["call_id"] == first
        for e in events
    )
    assert any(
        e["event_type"] == "model.correction.requested"
        and e["details"]["correction_of_call_id"] == first
        for e in events
    )
    assert any(
        e["event_type"] == "model.contract.validated" and e["details"]["call_id"] == second
        for e in events
    )
    assert any(
        e["event_type"] == "model.decision.accepted" and e["details"]["call_id"] == second
        for e in events
    )
    assert "PRIVATE" not in json.dumps(events)


def test_fast_completion_and_retry_are_saved_before_slow_parallel_agent_finishes():
    release_slow = Event()
    retry_seen = Event()
    fast_completed = Event()
    events = []

    class Fast:
        name = AgentName.SPENDING
        calls = 0

        def run_task(self, task):
            self.calls += 1
            if self.calls == 1:
                raise ModelGatewayError("PRIVATE transient")
            assert retry_seen.is_set(), "retry event must precede the actual retry"
            return CompletedInvocation(
                result=AgentResult(agent=self.name, summary="Spending reviewed")
            )

    class Slow:
        name = AgentName.BUDGET

        def run_task(self, task):
            assert release_slow.wait(3), "fast completion was withheld behind the batch"
            return CompletedInvocation(
                result=AgentResult(agent=self.name, summary="Budget reviewed")
            )

    def receive(event):
        events.append(event)
        if event["event_type"] == "task.retry_scheduled":
            retry_seen.set()
        if event["event_type"] == "task.completed" and event.get("actor") == "spending":
            fast_completed.set()
            release_slow.set()

    sink = event_sink.set(receive)
    try:
        AgentOrchestrator(
            config=Settings(MODEL_PROVIDER="local_fixture", RETRY_BACKOFF_SECONDS=0),
            gateway=LocalFixtureModelGateway(),
            agents={AgentName.SPENDING: Fast(), AgentName.BUDGET: Slow()},
        ).handle(
            CoachRequest(
                user_id="u",
                session_id="s",
                message="Review spending and budget",
                requested_agents=["spending", "budget"],
            )
        )
    finally:
        release_slow.set()
        event_sink.reset(sink)
    assert fast_completed.is_set()
    assert "PRIVATE" not in json.dumps(events)
    assert any(
        "queue_duration_ms" in e["details"] for e in events if e["event_type"] == "task.started"
    )


def test_routing_override_has_safe_before_after_and_rule():
    result = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"), gateway=LocalFixtureModelGateway()
    ).handle(
        CoachRequest(
            user_id="u",
            session_id="s",
            requested_agents=["budget"],
            message="Create a goal for a home",
        )
    )
    overrides = [e for e in result.audit["events"] if e["event_type"] == "routing.override_applied"]
    goal = next(
        e["details"]
        for e in overrides
        if e["details"]["rule_id"] == "GOAL_CAPTURE_REQUIRES_SPECIALIST"
    )
    assert goal["before"]["selected_agents"] == ["budget"]
    assert "goal_strategy" in goal["after"]["selected_agents"]
    assert "Create a goal" not in str(goal)


def test_execution_timing_excludes_retry_backoff(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("app.orchestrator.perf_counter", lambda: clock[0])
    monkeypatch.setattr(
        "app.orchestrator.sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    class RetryAgent:
        calls = 0

        def run_task(self, task):
            self.calls += 1
            clock[0] += 3
            if self.calls == 1:
                raise ModelGatewayError("PRIVATE")
            return CompletedInvocation(result=AgentResult(agent="spending", summary="Reviewed"))

    orchestrator = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture", RETRY_BACKOFF_SECONDS=2),
        gateway=LocalFixtureModelGateway(),
    )
    _, _, events, duration = orchestrator._execute_task(
        AgentTask(agent="spending", sanitized_message="Review"),
        RetryAgent(),
        submitted_at=8.0,
    )
    started = next(e.details for e in events if e.event_type == "task.started")
    finished = next(e.details for e in events if e.event_type == "task.execution.finished")
    assert started["queue_duration_ms"] == 2000
    assert finished["execution_duration_ms"] == 6000
    assert finished["backoff_duration_ms"] == 2000
    assert finished["duration_ms"] == duration == 8000


def test_unexpected_agent_failure_emits_safe_metadata_before_propagating():
    class BrokenAgent:
        def run_task(self, task):
            raise RuntimeError("PRIVATE exception")

    events = []
    sink = event_sink.set(events.append)
    try:
        orchestrator = AgentOrchestrator(
            config=Settings(MODEL_PROVIDER="local_fixture"),
            gateway=LocalFixtureModelGateway(),
        )
        with pytest.raises(RuntimeError, match="PRIVATE"):
            orchestrator._execute_task(
                AgentTask(agent="spending", sanitized_message="Review"), BrokenAgent()
            )
    finally:
        event_sink.reset(sink)
    failure = next(e for e in events if e["event_type"] == "task.attempt.failed")
    assert failure["details"]["exception_type"] == "RuntimeError"
    assert failure["details"]["retryable"] is False
    assert "PRIVATE" not in json.dumps(events)
