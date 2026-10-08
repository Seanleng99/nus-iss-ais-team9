"""Elapsed time never silently disables an otherwise permitted education repair."""

import json

import pytest
from test_hybrid_investment_education import FixedRetriever, HybridGateway, request, source

import app.core.deadline as deadline_module
import app.orchestrator as orchestrator_module
from app.core.config import Settings
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator


class ReviewGateway(HybridGateway):
    def __init__(self, clock, *, category="factual_qualification", final_blocked=False):
        super().__init__()
        self.clock = clock
        self.category = category
        self.final_blocked = final_blocked
        self.reviews = 0

    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance"):
            self.calls.append(kwargs)
            self.reviews += 1
            if self.reviews == 1:
                self.clock["elapsed"] = 25
            repairable = self.category == "factual_qualification"
            blocked = not repairable or self.reviews == 1 or self.final_blocked
            return json.dumps({
                "blocked": blocked, "request_allowed": self.category != "prohibited_request",
                "complete": True, "financial_language_safe": repairable,
                "missing_points": [],
                "blocking_issues": [{"section_id": "investment_education" if repairable else "request",
                                     "requirement": "Preserve the source institution caveat."}] if blocked else [],
                "block_categories": [self.category] if blocked else [],
                "summary": "Independent source qualification review.",
                "rationale": ["The explanatory scope was checked."],
                "policy_notes": ["The draft requires a qualification."] if blocked else [],
                "confidence": 0.9,
            })
        return super().generate(**kwargs)


def coach(gateway, *, deadline=None):
    options = {"WORKFLOW_TIMEOUT_SECONDS": deadline} if deadline is not None else {}
    return AgentOrchestrator(
        config=Settings(_env_file=None, MODEL_PROVIDER="local_fixture", **options),
        gateway=gateway, education_retriever=FixedRetriever([source()]),
    )


@pytest.mark.parametrize("deadline,final_blocked", [(None, False), (None, True), (20, False)])
def test_twenty_five_second_review_can_repair_once_with_default_window_and_fresh_final_review(
    monkeypatch, deadline, final_blocked
):
    monkeypatch.delenv("AGENT_TIMEOUT_SECONDS", raising=False)
    clock = {"elapsed": 0}
    monkeypatch.setattr(orchestrator_module, "perf_counter", lambda: clock["elapsed"])
    monkeypatch.setattr(deadline_module, "perf_counter", lambda: clock["elapsed"])
    gateway = ReviewGateway(clock, final_blocked=final_blocked)
    if deadline is not None:
        with pytest.raises(ModelGatewayError) as failure:
            coach(gateway, deadline=deadline).handle(request("Explain ETFs."))
        assert failure.value.code == "WORKFLOW_TIMEOUT"
        assert gateway.reviews == 1
        assert len(gateway.calls_for("agent_investment_education")) == 1
        return
    response = coach(gateway, deadline=deadline).handle(request("Explain ETFs."))
    events = [event["event_type"] for event in response.audit["events"]]
    if deadline is None:
        assert gateway.reviews == 2
        assert len(gateway.calls_for("agent_investment_education")) == 2
        assert events.count("education.completeness.repair") == 1
        assert response.blocked == final_blocked
        repaired_input = json.loads(gateway.calls_for("agent_investment_education")[1]["user_prompt"])
        assert "Preserve the source institution caveat." in repaired_input["message"]
        assert repaired_input["grounding"]["contexts"]
    else:
        assert gateway.reviews == 1
        assert len(gateway.calls_for("agent_investment_education")) == 1
        assert "education.completeness.repair" not in events
        assert response.blocked


@pytest.mark.parametrize("category", ["personal_advice", "prohibited_request"])
def test_unsafe_or_disallowed_review_never_repairs_even_inside_extended_window(monkeypatch, category):
    monkeypatch.delenv("AGENT_TIMEOUT_SECONDS", raising=False)
    clock = {"elapsed": 0}
    monkeypatch.setattr(orchestrator_module, "perf_counter", lambda: clock["elapsed"])
    monkeypatch.setattr(deadline_module, "perf_counter", lambda: clock["elapsed"])
    gateway = ReviewGateway(clock, category=category)
    response = coach(gateway).handle(request("Explain ETFs."))
    assert response.blocked
    assert gateway.reviews == 1
    assert len(gateway.calls_for("agent_investment_education")) == 1
    assert not any(event["event_type"] == "education.completeness.repair" for event in response.audit["events"])


def test_prohibited_user_request_never_reaches_repair_writer(monkeypatch):
    monkeypatch.delenv("AGENT_TIMEOUT_SECONDS", raising=False)
    clock = {"elapsed": 0}
    monkeypatch.setattr(orchestrator_module, "perf_counter", lambda: clock["elapsed"])
    monkeypatch.setattr(deadline_module, "perf_counter", lambda: clock["elapsed"])
    gateway = ReviewGateway(clock)
    response = coach(gateway).handle(request("Choose which stock I should buy today."))
    assert response.blocked
    assert len(gateway.calls_for("agent_investment_education")) <= 1
    assert not any(event["event_type"] == "education.completeness.repair" for event in response.audit["events"])


def test_positive_remaining_time_does_not_admit_a_repair_that_cannot_fit_observed_latency(monkeypatch):
    import app.models.gateway as gateway_module
    clock = {"elapsed": 0}
    monkeypatch.setattr(orchestrator_module, "perf_counter", lambda: clock["elapsed"])
    monkeypatch.setattr(deadline_module, "perf_counter", lambda: clock["elapsed"])
    monkeypatch.setattr(gateway_module, "perf_counter", lambda: clock["elapsed"])
    gateway = ReviewGateway(clock)
    response = coach(gateway, deadline=55).handle(request("Explain ETFs."))
    assert response.blocked and gateway.reviews == 1
    assert len(gateway.calls_for("agent_investment_education")) == 1
    event = next(event for event in response.audit["events"]
                 if event["event_type"] == "education.completeness.repair_decision")
    assert "REPAIR_DEADLINE_EXCEEDED" in event["details"]["repair_blockers"]
    assert event["details"]["estimated_repair_duration_ms"] >= 50000
    assert event["details"]["remaining_duration_ms"] == 30000
