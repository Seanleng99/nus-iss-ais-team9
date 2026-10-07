"""Semantic repair reuses sealed evidence, never user-supplied grounding authority."""

import json
from copy import deepcopy

import pytest
from test_education_semantic_coverage import (
    QUOTE,
    RecordingRetriever,
    ScriptedSemanticGateway,
    task,
)

from app.agents.investment_education import InvestmentEducationAgent
from app.core.config import Settings
from app.core.education_grounding import EducationGroundingSnapshot
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentResult, CoachRequest
from app.models.gateway import ModelGatewayError, ModelGeneration
from app.orchestrator import AgentOrchestrator


class RepairGateway(ScriptedSemanticGateway):
    def __init__(self, *, outcome="allowed"):
        super().__init__()
        self.outcome = outcome
        self.writers = 0
        self.reviews = 0

    def generate(self, **kwargs):
        component = kwargs["system_prompt"].splitlines()[0].removeprefix("PROMPT_ID: ")
        if component == "risk_compliance":
            self.calls.append(kwargs)
            self.reviews += 1
            blocked = self.reviews == 1 or self.outcome == "blocked"
            raw = json.dumps({
                "blocked": blocked, "request_allowed": True, "complete": True,
                "financial_language_safe": True, "missing_points": [],
                "blocking_issues": [{"section_id": "investment_education",
                                     "requirement": "Retain the source conditions."}] if blocked else [],
                "block_categories": ["factual_qualification"] if blocked else [],
                "summary": "The source qualification was reviewed.",
                "rationale": ["Source scope and conceptual completeness were checked."],
                "policy_notes": ["The initial draft requires a qualification."] if blocked else [],
                "confidence": 0.9,
            })
        else:
            raw = super().generate(**kwargs)
            if component == "agent_investment_education":
                self.writers += 1
                if self.writers == 2 and self.outcome == "unavailable":
                    raise ModelGatewayError(
                        "Synthetic correction unavailable.", code="OPENAI_AUTHENTICATION_FAILED",
                    )
        # Initial usage is 25,345. A repeated plan/assessment adds 8,393 and
        # would exhaust 40k; reusing it leaves 38,115 for the whole reviewed run.
        input_tokens, output_tokens = {
            "router": (4100, 82), "education_query_planner": (5500, 99),
            "education_answerability": (2700, 94), "agent_investment_education": (4200, 900),
            "risk_compliance": (6070, 1600),
        }.get(component, (100, 10))
        return ModelGeneration(raw, usage={
            "inputTokens": input_tokens, "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
        })


def calls_for(gateway, role):
    return [call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: " + role + "\n")]


@pytest.mark.parametrize("outcome", ["allowed", "blocked", "unavailable"])
def test_repair_does_not_repeat_semantic_assessment_and_still_requires_independent_review(outcome):
    gateway = RepairGateway(outcome=outcome)
    response = AgentOrchestrator(
        config=Settings(_env_file=None, MODEL_PROVIDER="openai", MAX_MODEL_TOKENS_PER_RUN=40000),
        gateway=gateway, education_retriever=RecordingRetriever(),
    ).handle(CoachRequest(
        user_id="synthetic", session_id="same-evidence-repair",
        message="Explain tracking error: why returns can differ from the tracked market measure.",
    ))
    assert len(calls_for(gateway, "education_query_planner")) == 1
    assert len(calls_for(gateway, "education_answerability")) == 1
    writers = calls_for(gateway, "agent_investment_education")
    assert len(writers) == 2
    assert gateway.reviews == (1 if outcome == "unavailable" else 2)
    original = json.loads(writers[0]["user_prompt"])["grounding"]
    repaired = json.loads(writers[1]["user_prompt"])["grounding"]
    assert repaired == original
    support = repaired["subquestion_coverage"][0]["supporting_passages"][0]
    ref = support["quote_ref"]
    assert repaired["contexts"][ref["context_index"]]["text"][ref["start"]:ref["end"]] == QUOTE
    assert "Retain the source conditions." in json.loads(writers[1]["user_prompt"])["message"]
    assert response.blocked == (outcome != "allowed")
    if outcome == "allowed":
        assert sum(call["total_tokens"] for call in response.audit["model_calls"]) == 38115
    else:
        assert not response.sources
        assert QUOTE not in response.answer
        assert all(result.blocked for result in response.agent_results)


class SchemaThenPolicyRepairGateway(RepairGateway):
    """One native-schema correction precedes a separately reviewed correction."""

    def __init__(self, *, unknown_component=None, small_initial=False, overrun=False,
                 prohibited_review=False, router_input_overhead=0):
        super().__init__()
        self.unknown_component = unknown_component
        self.small_initial = small_initial
        self.overrun = overrun
        self.prohibited_review = prohibited_review
        self.router_input_overhead = router_input_overhead

    def generate(self, **kwargs):
        component = kwargs["system_prompt"].splitlines()[0].removeprefix("PROMPT_ID: ")
        generation = super().generate(**kwargs)
        raw = str(generation)
        if component == "agent_investment_education" and self.writers == 1:
            payload = json.loads(raw)
            payload["source_ids"] = ["unapproved-source"]
            raw = json.dumps(payload)
        if component == "risk_compliance" and self.prohibited_review:
            payload = json.loads(raw)
            payload.update(request_allowed=False, blocked=True,
                           block_categories=["prohibited_request"],
                           blocking_issues=[{"section_id": "request",
                                             "requirement": "Do not fulfill the prohibited request."}])
            raw = json.dumps(payload)
        if component == self.unknown_component:
            return raw
        # Recorded live usage: six calls consumed 25,883 tokens. The first
        # schema-invalid writer is already paid for, but will not be repeated.
        usage = {
            "router": (3026, 290), "education_query_planner": (5598, 63),
            "education_answerability": (2247, 72), "risk_compliance": (3476, 633),
            "agent_investment_education": (4324, 505) if self.writers == 1 else (5392, 257),
        }
        if self.small_initial:
            usage.update(router=(700, 80), education_query_planner=(1500, 60),
                         education_answerability=(1000, 60))
        input_tokens, output_tokens = usage[component]
        if component == "router":
            input_tokens += self.router_input_overhead
        if self.overrun and component == "agent_investment_education" and self.writers == 3:
            input_tokens, output_tokens = 14000, 1000
        return ModelGeneration(raw, usage={
            "inputTokens": input_tokens, "outputTokens": output_tokens,
            "totalTokens": input_tokens + output_tokens,
        })


def run_schema_then_policy_repair(gateway, **settings):
    return AgentOrchestrator(
        config=Settings(_env_file=None, MODEL_PROVIDER="openai", **settings),
        gateway=gateway, education_retriever=RecordingRetriever(),
    ).handle(CoachRequest(
        user_id="synthetic", session_id="schema-then-reviewed-correction",
        message="Explain tracking error: why returns can differ from the tracked market measure.",
    ))


@pytest.mark.parametrize("router_input_overhead", [0, 100])
def test_admission_counts_all_consumed_usage_but_estimates_only_the_latest_writer_review_pair(
    router_input_overhead,
):
    gateway = SchemaThenPolicyRepairGateway(router_input_overhead=router_input_overhead)
    response = run_schema_then_policy_repair(gateway)
    calls = response.audit["model_calls"]
    assert sum(call["total_tokens"] for call in calls[:6]) == 25883 + router_input_overhead
    assert sum(call["total_tokens"] for call in calls) == 35641 + router_input_overhead
    assert len(calls_for(gateway, "education_query_planner")) == 1
    assert len(calls_for(gateway, "education_answerability")) == 1
    assert gateway.writers == 3
    assert gateway.reviews == 2
    assert not response.blocked
    assert len([event for event in response.audit["events"]
                if event["event_type"] == "education.completeness.repair"]) == 1
    writer_payloads = [json.loads(call["user_prompt"]) for call in
                      calls_for(gateway, "agent_investment_education")]
    assert writer_payloads[0]["grounding"] == writer_payloads[2]["grounding"]


@pytest.mark.parametrize("unknown_component", [
    "router", "education_query_planner", "agent_investment_education", "risk_compliance",
])
def test_unknown_real_provider_usage_cannot_admit_a_review_correction(unknown_component):
    gateway = SchemaThenPolicyRepairGateway(unknown_component=unknown_component)
    response = run_schema_then_policy_repair(gateway)
    assert response.blocked
    assert gateway.writers == 2
    assert gateway.reviews == 1
    assert not response.sources
    assert not any(event["event_type"] == "education.completeness.repair"
                   for event in response.audit["events"])


def test_explicit_20k_budget_refuses_correction_even_when_initial_review_fits():
    gateway = SchemaThenPolicyRepairGateway(small_initial=True)
    response = run_schema_then_policy_repair(gateway, MAX_MODEL_TOKENS_PER_RUN=20000)
    assert sum(call["total_tokens"] for call in response.audit["model_calls"]) == 17987
    assert response.blocked
    assert gateway.writers == 2
    assert gateway.reviews == 1
    assert not any(event["event_type"] == "education.completeness.repair"
                   for event in response.audit["events"])


def test_estimate_never_overrides_the_actual_token_cap_or_releases_an_unreviewed_correction():
    gateway = SchemaThenPolicyRepairGateway(overrun=True)
    response = run_schema_then_policy_repair(gateway, MAX_MODEL_TOKENS_PER_RUN=40000)
    assert response.blocked
    assert gateway.writers == 3
    assert gateway.reviews == 1
    assert sum(call["total_tokens"] for call in response.audit["model_calls"]) == 40883
    assert not response.sources
    assert QUOTE not in response.answer
    assert any(event["event_type"] == "education.completeness.repair_unavailable"
               for event in response.audit["events"])


def test_prohibited_review_cannot_repair_even_with_sufficient_budget_and_private_grounding():
    gateway = SchemaThenPolicyRepairGateway(prohibited_review=True)
    response = run_schema_then_policy_repair(gateway)
    assert response.blocked
    assert gateway.writers == 2
    assert gateway.reviews == 1
    assert not any(event["event_type"] == "education.completeness.repair"
                   for event in response.audit["events"])


def test_correction_keeps_call_reserve_for_bounded_contract_repairs():
    gateway = SchemaThenPolicyRepairGateway()
    response = run_schema_then_policy_repair(gateway, MAX_MODEL_CALLS_PER_RUN=9)
    assert response.blocked
    assert gateway.writers == 2
    assert gateway.reviews == 1


def original_grounding():
    original_task = task("Explain tracking error.")
    agent = InvestmentEducationAgent(
        ScriptedSemanticGateway(), PromptCatalog(), 0.2, 1600, RecordingRetriever(),
    )
    grounding = agent._ground(original_task, original_task.sanitized_message)
    return original_task, grounding, original_task._education_grounding_snapshot


@pytest.mark.parametrize("field,value", [
    ("sources", []), ("contexts", []), ("corpus_version", "other@v1"),
    ("scope", "Personal recommendations"), ("fallback_topics", ["CPF Investment Scheme"]),
    ("coverage_source_ids", ["invented-source"]),
])
def test_repair_rejects_changed_source_corpus_or_scope(field, value):
    original_task, grounding, snapshot = original_grounding()
    changed = deepcopy(grounding)
    changed[field] = value
    with pytest.raises(ModelGatewayError) as failed:
        snapshot.authorize_result(original_task, changed)
    assert failed.value.code == "INVALID_EDUCATION_REPAIR_CONTEXT"


@pytest.mark.parametrize("change", ["task", "question", "language", "prompt", "prompt_content", "corpus", "seal"])
def test_repair_cannot_reuse_another_task_or_modified_internal_snapshot(change):
    original_task, _grounding, snapshot = original_grounding()
    prompt_version = snapshot.prompt_version
    prompt_content_hash = snapshot.prompt_content_hash
    corpus_version = "investment-education-sg@test-v1"
    message = original_task.sanitized_message
    if change == "task":
        original_task.task_id = "different-task"
    elif change == "question":
        message = "Explain a different mechanism."
    elif change == "language":
        original_task.context_features["response_language"] = "zh"
    elif change == "prompt":
        prompt_version = "v7"
    elif change == "prompt_content":
        prompt_content_hash = "changed-under-the-same-release-label"
    elif change == "corpus":
        corpus_version = "changed@v1"
    else:
        snapshot.grounding["contexts"][0]["text"] = "An invented promotion of a source."
    with pytest.raises(ModelGatewayError) as failed:
        snapshot.for_repair(
            original_task, sanitized_message=message, prompt_version=prompt_version, prompt_content_hash=prompt_content_hash,
            expected_corpus_version=corpus_version,
        )
    assert failed.value.code == "INVALID_EDUCATION_REPAIR_CONTEXT"


def test_internal_snapshot_is_not_serialized_and_each_repair_gets_an_independent_copy():
    original_task, grounding, snapshot = original_grounding()
    assert isinstance(snapshot, EducationGroundingSnapshot)
    repaired_task = original_task.model_copy(deep=True)
    repaired_task.context_features["missing_points"] = ["Retain the source conditions."]
    snapshot.authorize_result(repaired_task, grounding)
    repaired = snapshot.for_repair(
        repaired_task, sanitized_message=repaired_task.sanitized_message,
        prompt_version=snapshot.prompt_version, prompt_content_hash=snapshot.prompt_content_hash, expected_corpus_version="investment-education-sg@test-v1",
    )
    repaired["contexts"][0]["text"] = "A temporary writer-side mutation."
    assert grounding["contexts"][0]["text"] == QUOTE
    assert snapshot.grounding["contexts"][0]["text"] == QUOTE
    assert "_education_grounding_snapshot" not in original_task.model_dump()
    result = AgentResult(agent="investment_education", summary="Reviewed.")
    result._education_grounding_snapshot = snapshot
    assert "_education_grounding_snapshot" not in result.model_dump()
    reconstructed = AgentResult.model_validate({**result.model_dump(), "_education_grounding_snapshot": grounding})
    assert reconstructed._education_grounding_snapshot is None


def test_user_context_marker_does_not_authorize_reusing_grounding():
    gateway = ScriptedSemanticGateway()
    original_task = task("Explain tracking error.")
    original_task.context_features["_education_grounding_snapshot"] = {
        "sources": [{"source_id": "invented-source"}], "coverage_source_ids": ["invented-source"],
    }
    agent = InvestmentEducationAgent(gateway, PromptCatalog(), 0.2, 1600, RecordingRetriever())
    grounding = agent._ground(original_task, original_task.sanitized_message)
    assert len(calls_for(gateway, "education_query_planner")) == 1
    assert len(calls_for(gateway, "education_answerability")) == 1
    assert grounding["coverage_source_ids"] == ["etf-source"]
