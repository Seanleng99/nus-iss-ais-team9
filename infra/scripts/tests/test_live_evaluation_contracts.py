"""Check authenticated state and exact decimal values, independent of formatting."""

from copy import deepcopy

import pytest

from infra.scripts.live_evaluation import evaluate_response


def evaluate(response, expected):
    passed, checks = evaluate_response(
        response, expected, expected_model_provider="openai",
        expected_model_id="model", expected_prompt_version="v6",
    )
    return passed, {item["check"]: item["passed"] for item in checks}


@pytest.mark.parametrize("status", ["preview", "needs_input"])
def test_unsaved_proposal_uses_authenticated_status_without_misreading_negation(status):
    response = {"answer": "Nothing has been saved. Please review the proposal.", "audit": {
        "action_status": status, "backend_outcomes": [{"status": status, "authority": "authenticated_backend"}],
    }}
    assert evaluate(response, {"action_status": ["preview", "needs_input"]})[0]


@pytest.mark.parametrize("status,authority,outcome_status", [
    ("saved", "authenticated_backend", "saved"),
    ("preview", "model", "preview"),
    ("preview", "authenticated_backend", "saved"),
    (None, "authenticated_backend", "preview"),
])
def test_saved_or_unattributed_state_cannot_pass_unsaved_proposal_contract(status, authority, outcome_status):
    response = {"answer": "Nothing has been saved.", "audit": {
        "action_status": status, "backend_outcomes": [{"status": outcome_status, "authority": authority}],
    }}
    assert not evaluate(response, {"action_status": ["preview", "needs_input"]})[0]


def input_guard_case():
    trace = "6f3f2d29-26f0-457b-96e4-8f8687e159af"
    response = {"answer": "Request withheld.", "blocked": True, "audit": {
        "trace_id": trace, "model_provider": "openai", "model_id": "model",
        "prompt_set_version": "v6", "model_call_count": 0, "model_calls": [],
        "guardrail_findings": ["prompt_injection:3"], "events": [
            {"trace_id": trace, "actor": "orchestrator", "event_type": "guardrail.evaluated",
             "details": {"allowed": False, "finding_count": 1}},
            {"trace_id": trace, "actor": "orchestrator", "event_type": "workflow.completed",
             "details": {"reason_code": "BOUNDARY_GUARDRAIL"}},
        ],
    }}
    expected = {"blocked": True, "deterministic_input_guard": True,
                "guardrail_finding_prefixes": ["prompt_injection:3"], "maximum_model_calls": 0}
    return response, expected


def test_actual_input_guard_block_proves_safety_without_a_model_invocation():
    response, expected = input_guard_case()
    passed, checks = evaluate(response, expected)
    assert passed
    assert checks["model_execution_or_deterministic_safety_evidence"]


@pytest.mark.parametrize("fault", [
    "missing_guard_event", "allowed_input", "missing_boundary", "wrong_trace", "missing_trace",
    "missing_findings", "wrong_prefix", "missing_explicit_expectation", "missing_call_count",
    "noninteger_call_count", "unproven_no_calls",
])
def test_refusal_text_or_partial_audit_cannot_substitute_for_input_guard_proof(fault):
    response, expected = input_guard_case()
    audit = response["audit"]
    if fault == "missing_guard_event":
        audit["events"] = audit["events"][1:]
    elif fault == "allowed_input":
        audit["events"][0]["details"]["allowed"] = True
    elif fault == "missing_boundary":
        audit["events"] = audit["events"][:1]
    elif fault == "wrong_trace":
        audit["events"][0]["trace_id"] = "other"
    elif fault == "missing_trace":
        audit.pop("trace_id")
    elif fault == "missing_findings":
        audit["guardrail_findings"] = []
    elif fault == "wrong_prefix":
        expected["guardrail_finding_prefixes"] = ["unrelated:"]
    elif fault == "missing_explicit_expectation":
        expected.pop("deterministic_input_guard")
    elif fault == "missing_call_count":
        audit.pop("model_call_count")
    elif fault == "noninteger_call_count":
        audit["model_call_count"] = False
    else:
        audit.pop("model_calls")
    passed, checks = evaluate(response, expected)
    assert not passed
    assert not checks["model_execution_or_deterministic_safety_evidence"]


def forecast_case():
    facts = {"start": "2026-02-01", "end": "2026-02-28", "currency": "SGD", "total": 1340.0,
             "occurrence_count": 6, "unknown_cadence_count": 1, "conditional_on_confirmed_terms": True}
    response = {"answer": "The recurring forecast totals SGD 1,340.00.", "audit": {
        "source": "recurring_forecast", "forecast_available": True,
        "recurring_forecast": facts, "action_status": "read_only_forecast",
        "backend_outcomes": [{"status": "read_only_forecast", "authority": "authenticated_backend"}],
    }}
    expected = {"answer_amounts": [{"currency": "SGD", "amount": "1340.00"}],
                "recurring_forecast": {**facts, "total": "1340.00"},
                "action_status": "read_only_forecast"}
    return response, expected


@pytest.mark.parametrize("amount", ["1,340.00", "1340.00", "1340.0", "1340"])
def test_forecast_numeric_value_accepts_standard_grouping_without_forcing_prose(amount):
    response, expected = forecast_case()
    response["answer"] = "The conditional forecast is SGD " + amount + "."
    assert evaluate(response, expected)[0]


@pytest.mark.parametrize("amount", ["13400.00", "1,34.00", "1,340.001", "-1,340.00", "1341.00"])
def test_forecast_does_not_accept_substrings_malformed_grouping_or_a_wrong_value(amount):
    response, expected = forecast_case()
    response["answer"] = "The forecast is SGD " + amount + "."
    passed, checks = evaluate(response, expected)
    assert not passed and not checks["answer_amounts"]


@pytest.mark.parametrize("field,value", [
    ("total", 1341.0), ("total", True), ("currency", "USD"), ("start", "2026-02-02"),
    ("end", "2026-03-01"), ("occurrence_count", 5), ("unknown_cadence_count", 0),
    ("conditional_on_confirmed_terms", False),
])
def test_correct_displayed_total_cannot_hide_wrong_authenticated_forecast_facts(field, value):
    response, expected = forecast_case()
    response["audit"]["recurring_forecast"] = deepcopy(response["audit"]["recurring_forecast"])
    response["audit"]["recurring_forecast"][field] = value
    passed, checks = evaluate(response, expected)
    assert not passed and not checks["recurring_forecast." + field]


def test_forecast_requires_explicit_display_currency_and_authenticated_source():
    response, expected = forecast_case()
    response["answer"] = "The forecast is USD 1,340.00."
    assert not evaluate(response, expected)[0]
    response["answer"] = "The forecast is SGD 1,340.00."
    response["audit"]["source"] = "model_estimate"
    assert not evaluate(response, expected)[0]
