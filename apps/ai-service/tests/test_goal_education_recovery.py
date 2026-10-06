"""Regressions for the persisted-goal follow-up and combined read-only assessment."""

import json
from copy import deepcopy

import pytest
from test_education_semantic_coverage import RecordingRetriever

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError, ModelGeneration
from app.orchestrator import AgentOrchestrator

TOPICS = ["diversification", "investment time horizon"]
PASSAGE = (
    "Diversification spreads investments across assets and reduces concentration risk; "
    "it cannot eliminate losses. Investment time horizon is the period before money is "
    "needed; a longer horizon does not guarantee a return."
)
CAPACITY = {
    "source": "confirmed_plan", "period_start": "2026-12-01", "currency": "SGD",
    "take_home_income": 5000, "planned_expenses": 2150, "estimated_savings_capacity": 1000,
    "unallocated_income": 1850, "calculation_method": "Confirmed monthly savings allocation",
    "budget_method": "flexible",
}
FOLLOW_UP = (
    "For that savings goal, explain diversification and investment time horizon using "
    "approved education sources. This is education only, with no investment recommendations."
)
COMBINED = (
    "Assess whether my Edge Course Test goal is affordable using my saved December 2026 "
    "budget capacity, and explain diversification and investment time horizon using "
    "approved education sources. This is read-only education, with no investment "
    "recommendations or record changes."
)


class GoalEducationGateway:
    def __init__(self, *, follow_up=False, outcome="allowed", unknown_usage=False):
        self.follow_up = follow_up
        self.outcome = outcome
        self.unknown_usage = unknown_usage
        self.calls = []
        self.writers = 0
        self.reviews = 0

    def calls_for(self, component):
        return [call for call in self.calls
                if call["system_prompt"].splitlines()[0] == "PROMPT_ID: " + component]

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        component = kwargs["system_prompt"].splitlines()[0].removeprefix("PROMPT_ID: ")
        payload = json.loads(kwargs["user_prompt"])
        if component == "router":
            value = {
                "selected_agents": ["investment_education"] if self.follow_up else [
                    "goal_strategy", "budget", "investment_education",
                ],
                "rationale": ["Answer the current read-only request."],
                "education_topics": TOPICS,
                "education_search_terms": TOPICS,
                # Reproduce the erroneous capture flag; the typed assessment
                # decision must override it before draft extraction can run.
                "budget_capture": not self.follow_up,
                "budget_capacity_query": not self.follow_up,
                "budget_scope": {"kind": "periods", "periods": ["2026-12-01"]},
                "follow_up_subject_position": 1 if self.follow_up else None,
            }
        elif component == "education_query_planner":
            value = {"subquestions": [{
                "question_id": f"q{index}", "topic": topic,
                "public_question": "Explain " + topic + ".", "query_terms": [topic],
            } for index, topic in enumerate(TOPICS, 1)]}
        elif component == "education_answerability":
            value = {"coverage": [{
                "question_id": f"q{index}", "status": "supported", "limitation": "",
                "supporting_passages": [{"source_id": "etf-source", "quote": PASSAGE}],
            } for index in (1, 2)]}
        elif component == "agent_investment_education":
            self.writers += 1
            if self.writers == 2 and self.outcome == "writer_unavailable":
                raise ModelGatewayError("Synthetic writer failure.", code="OPENAI_AUTHENTICATION_FAILED")
            value = {
                "summary": (PASSAGE if self.writers == 2 else
                            "Diversification spreads investments across assets. Investment time "
                            "horizon is the period before money is needed.") + " [source:etf-source]",
                "source_ids": ["etf-source"], "rationale": ["Approved evidence explains the concepts."],
                "confidence": 0.9, "uncertainties": [], "general_knowledge": [],
            }
        elif component in {"agent_goal_strategy", "agent_budget"}:
            grounding = payload["grounding"]
            assert not grounding.get("contexts")
            assert "answers the educational part" in kwargs["system_prompt"]
            assert "Do not say education sources were not supplied" in kwargs["system_prompt"]
            if component == "agent_goal_strategy":
                assert grounding["combined_feasibility"]["monthly_shortfall"] == 0
                summary = (
                    "Edge Course Test requires SGD 1,000 monthly for 12 months. December 2026 "
                    "saved capacity is SGD 1,000, with no shortfall, conditional on sustaining "
                    "that shared monthly pool. Unallocated income is not assigned to this goal."
                )
            else:
                assert "Do not assess the goal, ask for its cost/timeframe" in kwargs["system_prompt"]
                assert grounding["capacity"]["estimated_savings_capacity"] == 1000
                summary = (
                    "The December 2026 confirmed plan allocates SGD 1,000 to savings from "
                    "SGD 5,000 income and SGD 2,150 planned expenses. SGD 1,850 remains "
                    "unallocated; the savings allocation is a plan, not observed cash."
                )
            value = {"summary": summary, "rationale": ["Saved capacity supports the arithmetic."],
                     "confidence": 0.9}
        elif component == "risk_compliance":
            self.reviews += 1
            if self.reviews == 2 and self.outcome == "reviewer_unavailable":
                raise ModelGatewayError("Synthetic reviewer failure.", code="OPENAI_AUTHENTICATION_FAILED")
            prohibited = self.outcome == "prohibited"
            blocked = self.reviews == 1 or self.outcome == "rejected" or prohibited
            value = {
                "blocked": blocked, "request_allowed": not prohibited, "complete": True,
                "repairable": blocked and not prohibited, "financial_language_safe": True,
                "missing_points": ["Retain the source risk and return qualifications."] if blocked else [],
                "block_categories": (["prohibited_request"] if prohibited else
                                     ["factual_qualification"]) if blocked else [],
                "summary": "The draft was independently reviewed.",
                "rationale": ["Source conditions and deterministic calculations were checked."],
                "policy_notes": ["The education text requires source qualifications."] if blocked else [],
                "confidence": 0.9,
            }
        else:
            value = json.loads(LocalFixtureModelGateway().generate(**kwargs))
        raw = json.dumps(value)
        if component == "router" and self.unknown_usage:
            return raw
        # Representative usage after removing duplicate education context from
        # financial writers and preserving their text without another rewrite.
        input_tokens, output_tokens = {
            "router": (3475, 667), "education_query_planner": (5711, 93),
            "education_answerability": (5637, 246), "agent_budget": (2400, 350),
            "agent_goal_strategy": (2400, 450), "agent_investment_education": (5149, 526),
            "risk_compliance": (6900, 400),
        }.get(component, (100, 10))
        return ModelGeneration(raw, usage={"inputTokens": input_tokens,
            "outputTokens": output_tokens, "totalTokens": input_tokens + output_tokens})


def ask(gateway, *, follow_up=False, version="v6", **settings):
    retriever = RecordingRetriever(PASSAGE)
    orchestrator = AgentOrchestrator(
        config=Settings(_env_file=None, MODEL_PROVIDER="openai", PROMPT_SET_VERSION=version, **settings),
        gateway=gateway, education_retriever=retriever,
    )
    values = {
        "user_id": "synthetic", "session_id": "goal-education",
        "message": FOLLOW_UP if follow_up else COMBINED,
        "snapshot": {"goals": [{"name": "Edge Course Test", "target_amount": {"amount": 12000},
                                "target_months": 12}]},
        "saved_budget_capacity": {"source": "unavailable", "period_start": "2026-10-01"},
        "budget_context": {"selected_period": "2026-10-01", "budget_periods": ["2026-12-01"],
                           "capacity_by_period": {"2026-12-01": CAPACITY}},
    }
    if follow_up:
        values["message_position"] = 3
        values["session_context"] = {"referents": [{
            "subject": "Edge Course Test", "agent": "goal_strategy", "source_position": 1,
            "source_quote": "my Edge Course Test goal", "education_topics": [],
        }]}
        values["conversation_context"] = [
            {"role": "user", "content": "Assess my Edge Course Test goal using December 2026 capacity."},
            {"role": "assistant", "content": "The goal assessment was completed."},
        ]
    request = CoachRequest.model_validate(values)
    original = deepcopy(request.model_dump())
    response = orchestrator.handle(request)
    assert request.model_dump() == original
    assert all("Edge Course Test" not in query and "12000" not in query for query in retriever.queries)
    return response


@pytest.mark.parametrize("version", ["v6", "v7"])
def test_goal_reference_preserves_new_education_intent_and_topics(version):
    gateway = GoalEducationGateway(follow_up=True)
    response = ask(gateway, follow_up=True, version=version)
    assert response.selected_agents == ["investment_education"]
    assert response.audit["follow_up"]["reason_code"] == "SEMANTIC_PERSISTED_REFERENCE"
    assert not response.blocked
    assert "cannot eliminate losses" in response.answer
    assert "does not guarantee a return" in response.answer
    assert not gateway.calls_for("agent_goal_strategy")
    assert not gateway.calls_for("agent_budget")
    writer = json.loads(gateway.calls_for("agent_investment_education")[0]["user_prompt"])
    assert writer["grounding"]["query_topics"] == TOPICS


@pytest.mark.parametrize("limit", [50000, 100000])
@pytest.mark.parametrize("version", ["v6", "v7"])
def test_combined_repair_preserves_calculations_and_evidence_within_configured_budget(limit, version):
    gateway = GoalEducationGateway()
    response = ask(gateway, version=version, MAX_MODEL_TOKENS_PER_RUN=limit)
    assert not response.blocked
    assert len(response.agent_results) == 4  # Three specialists and independent Compliance.
    assert gateway.writers == gateway.reviews == 2
    for component in ("education_query_planner", "education_answerability", "agent_budget", "agent_goal_strategy"):
        assert len(gateway.calls_for(component)) == 1
    assert not gateway.calls_for("budget_capture")
    assert not gateway.calls_for("synthesizer")
    for result in response.agent_results:
        assert "budget_draft" not in result.data and "goal_draft" not in result.data
        # Server renders source markers, while calculation text is kept verbatim.
        if result.agent in {"budget", "goal_strategy"}:
            assert result.summary in response.answer
    goal = next(item for item in response.agent_results if item.agent == "goal_strategy")
    assert goal.data["monthly_savings_capacity"] == {**CAPACITY, "explicit_scope": True}
    assert goal.data["combined_feasibility"]["monthly_capacity"] == 1000
    assert goal.data["combined_feasibility"]["monthly_shortfall"] == 0
    reviews = [json.loads(call["user_prompt"]) for call in gateway.calls_for("risk_compliance")]
    financial_before = [item for item in reviews[0]["agent_results"] if item["agent"] != "investment_education"]
    financial_after = [item for item in reviews[1]["agent_results"] if item["agent"] != "investment_education"]
    assert financial_before == financial_after
    assert {item["agent"] for item in reviews[1]["agent_results"]} == {
        "goal_strategy", "budget", "investment_education",
    }
    writers = [json.loads(call["user_prompt"]) for call in gateway.calls_for("agent_investment_education")]
    assert writers[0]["grounding"] == writers[1]["grounding"]
    assert "Assess whether" not in writers[0]["message"]
    assert "budget capacity" not in writers[0]["message"]
    assert "Limit uncertainties to this education evidence" in writers[0]["message"]
    assert "Retain the source risk and return qualifications." in writers[1]["message"]
    assert sum(call["total_tokens"] for call in response.audit["model_calls"]) == 47379
    decision = next(event["details"] for event in response.audit["events"]
                    if event["event_type"] == "education.completeness.repair_decision")
    assert decision["reason_code"] == "REPAIR_ELIGIBLE" and decision["repair_blockers"] == []
    assert decision["used_tokens"] + decision["estimated_repair_tokens"] < decision["token_limit"]


@pytest.mark.parametrize("outcome", ["writer_unavailable", "reviewer_unavailable", "rejected"])
def test_failed_combined_repair_retains_original_review_and_diagnostics_without_releasing_draft(outcome):
    gateway = GoalEducationGateway(outcome=outcome)
    response = ask(gateway)
    assert response.blocked
    assert gateway.writers == 2
    assert gateway.reviews == (1 if outcome == "writer_unavailable" else 2)
    assert not response.sources
    assert PASSAGE not in response.answer
    assert len(response.agent_results) == 4 and all(item.blocked for item in response.agent_results)
    events = response.audit["events"]
    assert any(event["event_type"] == "compliance.completed"
               and event["details"]["review_block_categories"] == ["factual_qualification"] for event in events)
    if outcome != "rejected":
        failure = next(event["details"] for event in events
                       if event["event_type"] == "education.completeness.repair_unavailable")
        assert failure["error_code"] == "OPENAI_AUTHENTICATION_FAILED"


@pytest.mark.parametrize("options,unknown_usage,reason", [
    ({"MAX_MODEL_TOKENS_PER_RUN": 40000}, False, "REPAIR_TOKEN_BUDGET_EXCEEDED"),
    ({"MAX_MODEL_CALLS_PER_RUN": 10}, False, "REPAIR_CALL_BUDGET_EXCEEDED"),
    ({}, True, "REPAIR_USAGE_UNAVAILABLE"),
])
def test_repair_diagnostics_separate_budget_and_usage_limits(options, unknown_usage, reason):
    gateway = GoalEducationGateway(unknown_usage=unknown_usage)
    response = ask(gateway, **options)
    assert response.blocked and gateway.writers == gateway.reviews == 1
    decision = next(event["details"] for event in response.audit["events"]
                    if event["event_type"] == "education.completeness.repair_decision")
    assert decision["reason_code"] == reason and reason in decision["repair_blockers"]
    assert "REPAIR_SPECIALIST_NOT_ELIGIBLE" not in decision["repair_blockers"]
    assert "REPAIR_GROUNDING_UNAVAILABLE" not in decision["repair_blockers"]
    assert decision["remaining_tokens"] == decision["token_limit"] - decision["used_tokens"]
    assert "Retain the source" not in json.dumps(response.audit)


def test_combined_prohibited_review_never_admits_correction():
    gateway = GoalEducationGateway(outcome="prohibited")
    response = ask(gateway)
    assert response.blocked and gateway.writers == gateway.reviews == 1
    decision = next(event["details"] for event in response.audit["events"]
                    if event["event_type"] == "education.completeness.repair_decision")
    assert "REPAIR_REQUEST_NOT_ALLOWED" in decision["repair_blockers"]
    assert not response.sources
