"""Structural regressions for the seven failures in the latest deployed run.

Scripted decisions exercise contracts and authority, not real-model accuracy.
"""

import json

import pytest
from test_conditional_financial_dependencies import RecordingGateway, request, run
from test_education_semantic_coverage import RecordingRetriever
from test_financial_review_repair import ask
from test_live_review_recovery import ClaimGateway, calls_for
from test_scoped_education_review import review, verdict

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.contracts import output_format, structured_contract
from app.models.gateway import LocalFixtureModelGateway, ModelGeneration
from app.orchestrator import AgentOrchestrator
from app.rag.answerability import PUBLIC_QUERY_CONCEPTS, EducationQueryPlan


@pytest.mark.parametrize("consumes_spending", [True, False])
def test_budget_planner_can_reconsider_router_hint_without_forcing_an_edge(consumes_spending):
    class Gateway(RecordingGateway):
        def generate(self, **kwargs):
            role = kwargs["system_prompt"].splitlines()[0]
            if role == "PROMPT_ID: dependency_planner":
                payload = json.loads(kwargs["user_prompt"])
                if payload["agent"] == "budget":
                    self.calls.append(kwargs)
                    assert payload["context_features"]["task_assignment"]["requires_spending"] is False
                    assert payload["allowed_requests"][0]["capability"] == "transaction_category_totals"
                    return json.dumps({"status": "needs_dependency" if consumes_spending else "ready",
                        "requests": [{key: value for key, value in payload["allowed_requests"][0].items()
                                      if key != "selection_guidance"}] if consumes_spending else [],
                        "questions": [], "reason_code": "APPROVED_CAPABILITY_REQUIRED" if consumes_spending else None})
            value = super().generate(**kwargs)
            if role == "PROMPT_ID: router":
                decision = json.loads(value)
                for assignment in decision["task_assignments"]:
                    assignment["requires_spending"] = False
                return json.dumps(decision)
            return value

    gateway = Gateway()
    message = ("Explain savings capacity using my budget and observed spending pressures." if consumes_spending
               else "Analyze spending by category. Independently explain my budget savings capacity.")
    response = run(request(message, ["budget", "spending"], capacity=True), gateway)
    assert not response.blocked
    edges = response.audit["dependency_edges"]
    assert [edge["capability"] for edge in edges] == (["transaction_category_totals"] if consumes_spending else [])
    writer = json.loads(calls_for(gateway, "agent_budget")[0]["user_prompt"])
    assert ("spending_context" in writer["grounding"]) == consumes_spending
    assert len(calls_for(gateway, "agent_spending")) == 1  # Reuse an already selected provider.


def test_writer_and_review_receive_each_historical_months_observed_dates():
    gateway = RecordingGateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        CoachRequest(user_id="u", session_id="coverage", message="Analyze recorded spending by category.",
            requested_agents=["spending"], snapshot={"period_start": "2026-10-01",
                "recent_transactions": [{"description": "Food", "category": "food",
                                         "amount": {"amount": 50}, "occurred_on": "2026-10-06"}],
                "historical_transactions": [{"description": "Food", "category": "food",
                    "amount": {"amount": 25}, "occurred_on": day} for day in ("2026-09-26", "2026-09-01")]}))
    assert not response.blocked
    writer = json.loads(calls_for(gateway, "agent_spending")[0]["user_prompt"])["grounding"]
    reviewer = json.loads(calls_for(gateway, "risk_compliance")[0]["user_prompt"])
    data = next(row["data"] for row in reviewer["agent_results"] if row["agent"] == "spending")
    assert writer["historical_months"] == data["historical_months"]
    row = data["historical_months"][0]
    assert row["period_end"] == "2026-09-30"
    assert row["first_recorded_on"] == "2026-09-01"
    assert row["last_recorded_on"] == "2026-09-26"
    assert row["records_complete"] is False and row["transaction_count"] == 2
    assert data["selected_month_coverage"]["last_recorded_on"] == "2026-10-06"


def test_query_planner_provider_schema_exposes_only_accepted_public_concepts():
    with structured_contract(EducationQueryPlan):
        schema = output_format()["schema"]["$defs"]["EducationSubquestion"]["properties"]
    assert schema["query_terms"]["items"]["enum"] == PUBLIC_QUERY_CONCEPTS
    assert "investment readiness emergency cash" in schema["topic"]["enum"]
    assert "liquidity" in PUBLIC_QUERY_CONCEPTS
    assert "my salary" not in PUBLIC_QUERY_CONCEPTS


def test_incomplete_review_uses_owned_issue_instead_of_duplicated_feedback_wording():
    decision = verdict()
    decision.update(complete=False, missing_points=["The time horizon caveat is missing."])
    result, gateway = review([decision])
    assert len(gateway.calls) == 1
    assert result.blocked and result.data["repairable"]
    assert result.data["missing_points"] == [decision["blocking_issues"][0]["requirement"]]


@pytest.mark.parametrize("action", ["ground_claim", "remove_claim"])
def test_quote_only_claim_location_resolves_offsets_and_still_requires_a_fresh_review(action):
    class Gateway(ClaimGateway):
        def generate(self, **kwargs):
            value = super().generate(**kwargs)
            if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance") and self.rounds == 1:
                decision = json.loads(value)
                payload = json.loads(kwargs["user_prompt"])
                issue = decision["blocking_issues"][0]
                issue.update(claim_quote=payload["draft_answer"], claim_start=None, claim_end=None)
                assert "The server calculates offsets" in kwargs["system_prompt"]
                return json.dumps(decision)
            return value
    gateway = Gateway(action)
    response = ask(gateway)
    assert not response.blocked and gateway.rounds == 2 and len(gateway.writes) == 2
    correction = gateway.writes[1]["review_corrections"][0]
    assert correction["original_claim"] == gateway.writes[1]["original_summary"]
    assert gateway.writes[0]["grounding"] == gateway.writes[1]["grounding"]


def test_budget_only_education_correction_preserves_capacity_and_source_authority():
    passage = "Liquidity concerns access to money when it is needed."
    claim = "Liquidity proves this money is available to withdraw now."
    message = "Explain my October 2026 confirmed savings capacity and why liquidity matters for that pool."

    class Gateway:
        def __init__(self):
            self.calls, self.reviews, self.writers = [], 0, 0

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            component = kwargs["system_prompt"].splitlines()[0]
            payload = json.loads(kwargs["user_prompt"])
            if component == "PROMPT_ID: router":
                value = {"selected_agents": ["budget"], "rationale": ["Budget owns the calculation and sourced context."],
                    "budget_capacity_query": True, "education_topics": ["liquidity"],
                    "education_search_terms": ["liquidity"],
                    "budget_scope": {"kind": "periods", "periods": ["2026-10-01"]},
                    "task_assignments": [{"agent": "budget", "question": message, "source_quotes": [message],
                        "requires_income": True, "requires_capacity": True, "requires_spending": False,
                        "education_topics": ["liquidity"], "operation": "analysis"}]}
            elif component == "PROMPT_ID: education_query_planner":
                value = {"subquestions": [{"question_id": "q1", "topic": "liquidity",
                    "public_question": "Why does liquidity matter for a savings pool?", "query_terms": ["liquidity"]}]}
            elif component == "PROMPT_ID: education_answerability":
                value = {"coverage": [{"question_id": "q1", "status": "supported", "limitation": "",
                    "supporting_passages": [{"source_id": "etf-source", "quote": passage}]}]}
            elif component == "PROMPT_ID: agent_budget":
                self.writers += 1
                assert payload["grounding"]["capacity"]["estimated_savings_capacity"] == 700
                summary = "Confirmed savings allocation is SGD 700. " + (claim if self.writers == 1 else
                    passage + " The allocation is a plan, not observed cash; actual account access was not supplied.")
                value = {"summary": summary + " [source:etf-source]", "source_ids": ["etf-source"],
                    "rationale": ["Saved allocation and carried general concept."], "confidence": 0.9}
            elif component == "PROMPT_ID: answer_correction":
                value = {"replacements": [{"issue_id": issue["issue_id"], "replacement":
                    passage + " The allocation is a plan, not observed cash; actual account access was not supplied."}
                    for issue in payload["issues"]]}
            elif component == "PROMPT_ID: risk_compliance":
                self.reviews += 1
                data = next(row["data"] for row in payload["agent_results"] if row["agent"] == "budget")
                assert data["capacity"]["estimated_savings_capacity"] == 700
                assert data["contexts"][0]["text"] == passage
                value = {"blocked": self.reviews == 1, "request_allowed": True, "complete": True,
                    "missing_points": [], "financial_language_safe": True,
                    "blocking_issues": [{"section_id": "budget", "category": "factual_qualification",
                        "requirement": "Distinguish the plan and general concept from unverified account access.",
                        "action": "qualify", "claim_quote": claim}] if self.reviews == 1 else [],
                    "block_categories": ["factual_qualification"] if self.reviews == 1 else [],
                    "policy_notes": ["Account access was not supplied."] if self.reviews == 1 else [],
                    "summary": "Independent evidence assessment.", "rationale": ["Inspect each evidence authority separately."],
                    "confidence": 0.9}
            else:
                return ModelGeneration(LocalFixtureModelGateway().generate(**kwargs),
                    usage={"inputTokens": 32, "outputTokens": 16, "totalTokens": 48})
            return ModelGeneration(json.dumps(value), usage={"inputTokens": 32, "outputTokens": 16, "totalTokens": 48})

    gateway = Gateway()
    retriever = RecordingRetriever(text=passage)
    req = request(message, ["budget"], capacity=True)
    req.snapshot.recent_transactions = []
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="openai"), gateway=gateway,
                                 education_retriever=retriever).handle(req)
    assert not response.blocked and response.selected_agents == ["budget"]
    assert gateway.reviews == 2 and gateway.writers == 1
    writers = [json.loads(call["user_prompt"])["grounding"] for call in calls_for(gateway, "agent_budget")]
    corrections = [json.loads(call["user_prompt"]) for call in calls_for(gateway, "answer_correction")]
    assert len(corrections) == 1
    assert writers[0] == corrections[0]["verified_grounding"][0]["data"]
    assert len(retriever.queries) == 1  # The correction never retrieves different evidence.
    assert claim not in response.answer and "SGD 700" in response.answer
    assert "actual account access was not supplied" in response.answer
