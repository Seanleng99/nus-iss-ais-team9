"""General contracts exposed by the deployed compound-question and repair failures."""

import json

import pytest
from test_conditional_financial_dependencies import RecordingGateway, request
from test_financial_review_repair import FinancialReviewGateway, ask

from app.core.config import Settings
from app.core.narrative_corrections import validate_text_corrections
from app.core.repair_budget import financial_repair_estimates
from app.models.gateway import ModelGatewayError, ModelGeneration
from app.orchestrator import AgentOrchestrator


def run(gateway, message, *, capacity=True):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        request(message, [], capacity=capacity))


class ReferenceGateway(RecordingGateway):
    def __init__(self, reference, subject, *, scope="current_message"):
        super().__init__()
        self.reference, self.subject, self.scope = reference, subject, scope

    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: dependency_planner"):
            payload = json.loads(kwargs["user_prompt"])
            if payload["agent"] == "budget":
                self.calls.append(kwargs)
                return json.dumps({"status": "needs_dependency", "requests": [
                    {key: value for key, value in option.items() if key != "selection_guidance"}
                    for option in payload["allowed_requests"]]})
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            self.calls.append(kwargs)
            message = json.loads(kwargs["user_prompt"])["message"]
            return json.dumps({"selected_agents": ["spending", "budget", "goal_strategy"],
                "reference_scope": self.scope, "reference_quote": self.reference,
                "reference_subject_quote": self.subject, "rationale": ["Current-message assessment data flow."],
                "budget_capacity_query": True,
                "task_assignments": [
                    {"agent": "spending", "question": message, "source_quotes": [message]},
                    {"agent": "budget", "question": message, "source_quotes": [message],
                     "requires_spending": True, "requires_capacity": True, "requires_income": False},
                    {"agent": "goal_strategy", "question": message, "source_quotes": [message],
                     "requires_capacity": True, "requires_income": False}]})
        return super().generate(**kwargs)


@pytest.mark.parametrize("message,reference,subject", [
    ("Analyze recorded purchases. Have Budget reconcile those totals. Use that Budget assessment to assess saved goals.",
     "that Budget assessment", "Have Budget reconcile those totals"),
    ("Compare expenses with my budget. Explain how that budget assessment affects all saved goals.",
     "that budget assessment", "Compare expenses with my budget"),
])
def test_current_message_reference_preserves_semantic_route_and_full_chain(message, reference, subject):
    response = run(ReferenceGateway(reference, subject), message)
    assert not response.blocked
    assert set(response.selected_agents) == {"spending", "budget", "goal_strategy"}
    assert response.audit["follow_up"] == {
        "status": "standalone", "reason_code": "SEMANTIC_CURRENT_MESSAGE_REFERENCE"}
    assert {edge["capability"] for edge in response.audit["dependency_edges"]} == {
        "transaction_category_totals", "monthly_savings_capacity"}


def test_current_message_reference_rejects_fabricated_antecedent_provenance():
    with pytest.raises(ModelGatewayError) as failure:
        run(ReferenceGateway("that Budget", "invented antecedent"), "Explain that Budget assessment.")
    assert failure.value.code == "INVALID_STRUCTURED_RESPONSE"


@pytest.mark.parametrize("message,reference,subject", [
    ("Explain that Budget assessment.", "that Budget", "Budget assessment"),
    ("Compare expenses. Explain that result and that result.", "that result", "Compare expenses"),
])
def test_current_message_reference_rejects_overlapping_or_nonunique_spans(message, reference, subject):
    with pytest.raises(ModelGatewayError) as failure:
        run(ReferenceGateway(reference, subject), message)
    assert failure.value.code == "INVALID_STRUCTURED_RESPONSE"


def test_ambiguous_override_reconciles_assignments_with_effective_specialist():
    response = run(ReferenceGateway(None, None, scope="ambiguous"), "Explain that.", capacity=False)
    assert response.selected_agents == ["investment_education"]
    route = next(e for e in response.audit["events"] if e["event_type"] == "routing.completed")
    assert [item["agent"] for item in route["details"]["task_assignments"]] == ["investment_education"]
    assert response.audit["follow_up"]["status"] == "ambiguous"
    assert response.agent_results[0].data["needs_input"]


class CapacityGateway(RecordingGateway):
    def __init__(self, reconcile):
        super().__init__()
        self.reconcile = reconcile

    def generate(self, **kwargs):
        role = kwargs["system_prompt"].splitlines()[0]
        payload = json.loads(kwargs["user_prompt"])
        if role == "PROMPT_ID: router":
            self.calls.append(kwargs)
            assert payload["available_capacity"]["source"] == "confirmed_plan"
            return json.dumps({"selected_agents": ["budget", "goal_strategy"], "rationale": ["Shared pool assessment."],
                "budget_capacity_query": True, "task_assignments": [
                    {"agent": "budget", "question": payload["message"], "source_quotes": [payload["message"]],
                     "requires_spending": True, "requires_capacity": True, "requires_income": False},
                    {"agent": "goal_strategy", "question": "Assess saved goal feasibility", "source_quotes": [payload["message"]],
                     "requires_capacity": True}]})
        if role == "PROMPT_ID: dependency_planner" and payload["agent"] == "budget":
            self.calls.append(kwargs)
            assert payload["available_inputs"]["confirmed_allocation_available"]
            assert payload["available_inputs"]["capacity_periods"] == [{
                "source": "confirmed_plan", "period_start": "2026-10-01"}]
            options = payload["allowed_requests"]
            return json.dumps({"status": "needs_dependency" if self.reconcile else "ready",
                               "requests": [{key: value for key, value in option.items() if key != "selection_guidance"}
                                            for option in options] if self.reconcile else []})
        return super().generate(**kwargs)


@pytest.mark.parametrize("reconcile,message", [
    (False, "Are all saved goals feasible against my confirmed monthly savings allocation?"),
    (True, "Reconcile recorded category totals against budget limits, then assess saved goal feasibility."),
])
def test_planner_can_reject_a_spending_hint_but_preserve_requested_reconciliation(reconcile, message):
    response = run(CapacityGateway(reconcile), message)
    capabilities = {e["capability"] for e in response.audit["dependency_edges"]}
    assert "monthly_savings_capacity" in capabilities
    assert ("transaction_category_totals" in capabilities) is reconcile


def test_composition_receives_verified_facts_and_spending_does_not_duplicate_its_grounding():
    gateway = RecordingGateway()
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway).handle(
        request("Analyze purchases independently of saved budget capacity.", ["spending", "budget"], capacity=True))
    assert not response.blocked
    writer_call = next(c for c in gateway.calls if c["system_prompt"].startswith("PROMPT_ID: agent_spending"))
    writer = json.loads(writer_call["user_prompt"])
    assert "analysis_results" not in json.loads(writer["message"])
    assert "analysis_results" not in writer_call["system_prompt"]
    assert "outer payload's grounding" in writer_call["system_prompt"]
    assert "budget limits are unavailable" in writer_call["system_prompt"]
    synthesis = json.loads(next(c for c in gateway.calls if c["system_prompt"].startswith("PROMPT_ID: synthesizer"))["user_prompt"])
    facts = {item["agent"]: item["data"] for item in synthesis["verified_grounding"]}
    assert facts["spending"]["category_totals"] == writer["grounding"]["category_totals"]
    assert facts["budget"]["capacity"]["source"] == "confirmed_plan"


def test_repair_forecast_uses_only_affected_latest_calls_with_growth_allowance():
    def call(component, inputs, outputs, maximum=3200):
        return {"component": component, "status": "completed", "input_tokens": inputs,
                "output_tokens": outputs, "max_output_tokens": maximum}
    calls = [call("agent_goal_strategy", 20000, 3000), call("agent_budget", 30000, 1000),
             call("agent_goal_strategy", 7000, 600), call("risk_compliance", 9000, 300)]
    estimates = financial_repair_estimates(calls, {"agent_goal_strategy", "risk_compliance"}, [])
    assert {e["component"] for e in estimates} == {"agent_goal_strategy", "risk_compliance"}
    total = sum(e["estimated_repair_tokens"] for e in estimates)
    assert 16000 < total < 34309
    assert 2 * (7000 + 9000 + 6400) > 34309
    assert all(e["output_tokens"] <= e["max_output_tokens"] for e in estimates)


class PreciseGateway(FinancialReviewGateway):
    def __init__(self, *, change_unaffected=False, repeated=False):
        super().__init__()
        self.change_unaffected, self.repeated = change_unaffected, repeated
        self.corrections = []

    def generate(self, **kwargs):
        role = kwargs["system_prompt"].splitlines()[0]
        payload = json.loads(kwargs["user_prompt"])
        if role == "PROMPT_ID: answer_correction":
            self.corrections.append(payload)
            value = {"replacements": [{"issue_id": issue["issue_id"], "replacement": "Coverage is incomplete."}
                                       for issue in payload["issues"]]}
            if self.change_unaffected:
                value["summary"] = "Recorded food is SGD 40. Coverage is incomplete."
            return json.dumps(value)
        if role == "PROMPT_ID: agent_spending":
            self.writes.append(payload)
            amount = 40 if self.change_unaffected and len(self.writes) > 1 else 50
            claim = "Coverage is complete." if len(self.writes) == 1 else "Coverage is incomplete."
            return json.dumps({"summary": f"Recorded food is SGD {amount}. {claim}",
                               "rationale": ["Recorded food amount."], "confidence": 0.8})
        if role == "PROMPT_ID: risk_compliance":
            self.rounds += 1
            if self.rounds == 1 or self.repeated:
                claim = "Coverage is complete." if self.rounds == 1 else "Coverage is incomplete."
                return json.dumps({"blocked": True, "request_allowed": True, "complete": True,
                    "missing_points": [], "financial_language_safe": True,
                    "blocking_issues": [{"section_id": "spending", "action": "qualify", "claim_quote": claim,
                                         "requirement": "Qualify the record coverage."}],
                    "block_categories": ["factual_qualification"], "policy_notes": ["Record coverage needs qualification."],
                    "summary": "Correction needed.", "rationale": ["Recorded data does not establish completeness."], "confidence": 1})
            # The parent would count another review; use its fixture base directly.
            from app.models.gateway import LocalFixtureModelGateway
            return LocalFixtureModelGateway.generate(self, **kwargs)
        return super().generate(**kwargs)


def test_claim_quote_resolves_a_targeted_edit_and_preserves_unchanged_amounts():
    gateway = PreciseGateway()
    response = ask(gateway)
    assert not response.blocked and gateway.rounds == 2
    assert response.answer == "Recorded food is SGD 50. Coverage is incomplete."
    correction = gateway.corrections[0]["issues"][0]
    assert correction["original_claim"] == "Coverage is complete."
    assert correction["claim_start"] == len("Recorded food is SGD 50. ")
    assert gateway.writes[0]["grounding"] == gateway.corrections[0]["verified_grounding"][0]["data"]
    assert len(gateway.writes) == 1
    assert "claim_quote" not in response.model_dump_json()
    assert "original_claim" not in response.model_dump_json()


def test_repair_cannot_change_an_unaffected_amount_or_release_an_unreviewed_draft():
    gateway = PreciseGateway(change_unaffected=True)
    response = ask(gateway)
    assert response.blocked and gateway.rounds == 1
    assert len(gateway.writes) == 1 and len(gateway.corrections) == 2
    assert "SGD 40" not in response.answer


def test_second_review_can_still_withhold_a_targeted_correction_without_more_rounds():
    gateway = PreciseGateway(repeated=True)
    response = ask(gateway)
    assert response.blocked and gateway.rounds == 2
    assert len(gateway.writes) == len(gateway.corrections) == 1


@pytest.mark.parametrize("location", ["missing", "fabricated", "mismatched_offsets"])
@pytest.mark.parametrize("mixed", [False, True])
def test_invalid_financial_claim_location_cannot_authorize_repair(location, mixed):
    class InvalidLocationGateway(PreciseGateway):
        def generate(self, **kwargs):
            value = super().generate(**kwargs)
            if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance"):
                verdict = json.loads(value)
                if verdict.get("blocking_issues"):
                    issue = verdict["blocking_issues"][0]
                    if mixed:
                        issue["category"] = "factual_qualification"
                        verdict["block_categories"].append("unverifiable_claim")
                        verdict["blocking_issues"].append({
                            "section_id": "spending", "category": "unverifiable_claim", "action": "remove_claim",
                            "claim_quote": "Recorded food is SGD 50.", "requirement": "Remove this claim."})
                    if location == "missing":
                        issue.pop("claim_quote")
                    elif location == "fabricated":
                        issue["claim_quote"] = "This text does not occur in the answer."
                    else:
                        issue.update(claim_start=0, claim_end=1)
                    return json.dumps(verdict)
            return value

    gateway = InvalidLocationGateway(repeated=True)
    response = ask(gateway)
    assert response.blocked and len(gateway.writes) == 1
    review = next(e["details"] for e in response.audit["events"] if e["event_type"] == "compliance.completed")
    assert "review_contract_unverified" in review["block_reasons"]


def test_patch_ranges_cover_only_identified_claims_including_multiple_edits():
    original = "Known amount 50. Claim A. Protected date. Claim B."
    ranges = [(original.index("Claim A"), original.index("Claim A") + len("Claim A")),
              (original.index("Claim B"), original.index("Claim B") + len("Claim B"))]
    validate_text_corrections(original, original.replace("Claim A", "Qualified A").replace("Claim B", "Qualified B"), ranges)
    with pytest.raises(ModelGatewayError):
        validate_text_corrections(original, original.replace("50", "40"), ranges)


class MeteredGateway(PreciseGateway):
    def __init__(self, *, unknown_usage=False, overrun=False):
        super().__init__()
        self.unknown_usage, self.overrun = unknown_usage, overrun

    def count_input_tokens(self, **kwargs):
        role = kwargs["system_prompt"].splitlines()[0]
        return {"PROMPT_ID: router": 36000, "PROMPT_ID: agent_spending": 6000,
                "PROMPT_ID: answer_correction": 7000,
                "PROMPT_ID: risk_compliance": 8000 if self.rounds == 0 else 8500}.get(role, 100)

    def generate(self, **kwargs):
        value = super().generate(**kwargs)
        role = kwargs["system_prompt"].splitlines()[0]
        if role == "PROMPT_ID: router":
            inputs, outputs = 36000, 1119
        elif role == "PROMPT_ID: agent_spending":
            if self.unknown_usage:
                return value
            inputs, outputs = 6000, 500
        elif role == "PROMPT_ID: answer_correction":
            inputs, outputs = 32000 if self.overrun else 7000, 600
        elif role == "PROMPT_ID: risk_compliance":
            inputs, outputs = (8000, 1500) if self.rounds == 1 else (8500, 800)
        else:
            inputs, outputs = 100, 100
        return ModelGeneration(value, usage={"inputTokens": inputs, "outputTokens": outputs,
                                             "totalTokens": inputs + outputs})


@pytest.mark.parametrize("limit,unknown,overrun,reason", [
    (80000, False, False, "REPAIR_ELIGIBLE"),
    (65000, False, False, "REPAIR_TOKEN_BUDGET_EXCEEDED"),
    (80000, True, False, "REPAIR_USAGE_UNAVAILABLE"),
    (80000, False, True, "REPAIR_ELIGIBLE"),
])
def test_metered_financial_repair_preserves_admission_and_actual_hard_limits(limit, unknown, overrun, reason):
    gateway = MeteredGateway(unknown_usage=unknown, overrun=overrun)
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="openai", MAX_MODEL_TOKENS_PER_RUN=limit),
                                 gateway=gateway).handle(
        request("Analyze October 2026 spending patterns.", ["spending"]))
    decision = next(e["details"] for e in response.audit["events"] if e["event_type"] == "claim.correction.decision")
    assert decision["reason_code"] == reason
    if reason == "REPAIR_ELIGIBLE" and not overrun:
        assert not response.blocked and gateway.rounds == 2
        assert len(gateway.writes) == len(gateway.corrections) == 1
        assert decision["used_tokens"] == 53119
        assert decision["estimated_repair_tokens"] < 26881
    else:
        assert response.blocked and gateway.rounds == 1
        assert "Coverage is incomplete" not in response.answer
    if overrun:
        failure = next(e for e in response.audit["events"] if e["event_type"] == "claim.correction.unavailable")
        assert failure["details"]["error_code"] == "MODEL_TOKEN_BUDGET_EXCEEDED"
