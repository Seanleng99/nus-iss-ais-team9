import json
import urllib.error
import urllib.parse
from uuid import UUID

import pytest

from infra.scripts import live_evaluation
from infra.scripts.live_evaluation import (
    LiveEndpointError,
    chat_session_delete_url,
    cleanup_session,
    enforce_thresholds,
    evaluate_response,
    run_live_evaluation,
)


@pytest.fixture(autouse=True)
def isolate_owned_fixture_apis(monkeypatch):
    """Most harness tests isolate coach responses; owned API tests override this."""
    def owned(_url, _key, _method, _payload, _timeout):
        return {"policy_version": "test-policy"} if _url.endswith("/data-lifecycle") else {}
    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", owned)


def test_chat_session_delete_url_preserves_api_prefix_and_encodes_ids() -> None:
    result = chat_session_delete_url(
        "https://example.test/api/coach?ignored=true",
        "live user",
        "session/one",
    )

    assert result == (
        "https://example.test/api/users/live%20user/chat-sessions/session%2Fone"
    )


def test_cleanup_treats_missing_synthetic_session_as_clean(monkeypatch) -> None:
    def missing(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example.test/session", 404, "Not Found", {}, None
        )

    monkeypatch.setattr(live_evaluation.urllib.request, "urlopen", missing)

    assert (
        cleanup_session(
            "https://example.test/api/coach", "secret", "user", "session", 1
        )
        is True
    )


def test_evaluate_response_checks_dependencies_model_and_prompt() -> None:
    response = {
        "blocked": False,
        "selected_agents": ["goal_strategy", "budget", "spending"],
        "agent_results": [],
        "sources": [],
        "audit": {
            "model_provider": "bedrock",
            "model_id": "apac.amazon.nova-lite-v1:0",
            "prompt_set_version": "v3",
            "model_calls": [{"component": "router"}],
            "dependency_resolutions": [
                {"capability": "monthly_savings_capacity", "resolution": "resolved"},
                {"capability": "transaction_category_totals", "resolution": "resolved"},
            ],
        },
    }

    passed, checks = evaluate_response(
        response,
        {
            "blocked": False,
            "dependency_capabilities": [
                "monthly_savings_capacity",
                "transaction_category_totals",
            ],
        },
        expected_model_provider="bedrock",
        expected_model_id="apac.amazon.nova-lite-v1:0",
        expected_prompt_version="v3",
    )

    assert passed is True
    assert all(check["passed"] for check in checks)


def test_evaluate_response_requires_grounded_sources() -> None:
    corpus_version = "investment-education-sg@2026-08-28.1"
    response = {
        "blocked": False,
        "agent_results": [
            {
                "agent": "investment_education",
                "data": {"evidence_status": "grounded"},
            }
        ],
        "sources": [
            {
                "source_id": "approved-source",
                "title": "Approved source",
                "issuing_organization": "Issuer",
                "canonical_url": "https://example.test/source",
                "published_at": "2026-08-28",
                "document_version": "2026-08-28",
                "checksum": f"sha256:{'a' * 64}",
                "corpus_version": corpus_version,
                "review_due_at": "2026-11-14",
            }
        ],
        "audit": {
            "model_provider": "bedrock",
            "model_id": "model",
            "prompt_set_version": "v3",
            "model_calls": [{"component": "router"}],
            "retrieval_corpus_versions": [corpus_version],
            "policy_corpus_versions": ["financial-coach-policy-sg@test-v1"],
            "policy_sources": [
                {
                    "source_id": "approved-policy",
                    "title": "Approved policy",
                    "issuing_organization": "AI Governance",
                    "canonical_url": "https://example.test/policy",
                    "published_at": "2026-08-29",
                    "document_version": "2026-08-29",
                    "checksum": f"sha256:{'b' * 64}",
                    "corpus_version": "financial-coach-policy-sg@test-v1",
                    "review_due_at": "2026-11-27",
                }
            ],
        },
    }

    passed, _ = evaluate_response(
        response,
        {
            "minimum_sources": 1,
            "source_provenance": True,
            "retrieval_corpus_version": corpus_version,
            "policy_source_provenance": True,
            "policy_corpus_version": "financial-coach-policy-sg@test-v1",
            "evidence_status": "grounded",
        },
        expected_model_provider="bedrock",
        expected_model_id="model",
        expected_prompt_version="v3",
    )

    assert passed is True


def test_evaluate_response_rejects_mismatched_corpus_provenance() -> None:
    response = {
        "blocked": False,
        "agent_results": [],
        "sources": [{"source_id": "source-without-provenance"}],
        "audit": {
            "model_provider": "bedrock",
            "model_id": "model",
            "prompt_set_version": "v3",
            "model_calls": [{"component": "router"}],
            "retrieval_corpus_versions": ["unexpected-corpus"],
        },
    }

    passed, checks = evaluate_response(
        response,
        {
            "source_provenance": True,
            "retrieval_corpus_version": "expected-corpus",
        },
        expected_model_provider="bedrock",
        expected_model_id="model",
        expected_prompt_version="v3",
    )

    assert passed is False
    failed = {check["check"] for check in checks if not check["passed"]}
    assert failed == {"source_provenance", "retrieval_corpus_version"}


def test_evaluate_response_checks_policy_guardrail_and_agent_boundaries() -> None:
    response = {
        "blocked": True,
        "selected_agents": ["investment_education"],
        "agent_results": [
            {
                "agent": "risk_compliance",
                "data": {},
                "policy_notes": ["regulated_advice:guaranteed return"],
            }
        ],
        "disclaimers": ["Educational use only"],
        "sources": [],
        "audit": {
            "guardrail_findings": ["email"],
            "model_provider": "bedrock",
            "model_id": "model",
            "prompt_set_version": "v3",
            "model_call_count": 3,
            "model_calls": [{"component": "risk_compliance"}],
            "dependency_resolutions": [],
        },
    }

    passed, checks = evaluate_response(
        response,
        {
            "blocked": True,
            "selected_agents": ["investment_education"],
            "forbidden_agents": ["budget"],
            "dependency_capabilities": [],
            "policy_finding_prefixes": ["regulated_advice:"],
            "guardrail_finding_prefixes": ["email"],
            "minimum_disclaimers": 1,
            "minimum_model_calls": 2,
            "maximum_model_calls": 4,
        },
        expected_model_provider="bedrock",
        expected_model_id="model",
        expected_prompt_version="v3",
    )

    assert passed is True
    assert all(check["passed"] for check in checks)


EXECUTION_CHECK = "model_execution_or_deterministic_safety_evidence"


@pytest.fixture
def deterministic_safety_case():
    finding = "regulated_advice:tell me exactly what to invest in"
    response = {
        "blocked": True,
        "selected_agents": ["investment_education"],
        "agent_results": [
            {
                "agent": "risk_compliance",
                "data": {},
                "policy_notes": [finding],
            }
        ],
        "disclaimers": ["Educational use only"],
        "sources": [],
        "audit": {
            "model_provider": "bedrock",
            "model_id": "apac.amazon.nova-lite-v1:0",
            "prompt_set_version": "v6",
            "model_calls": [],
            "model_call_count": 0,
        },
    }
    expected = {
        "blocked": True,
        "selected_agents": ["investment_education"],
        "policy_finding_prefixes": [finding],
        "minimum_disclaimers": 1,
    }
    return response, expected


def evaluate_safety_case(response, expected):
    passed, checks = evaluate_response(
        response,
        expected,
        expected_model_provider="bedrock",
        expected_model_id="apac.amazon.nova-lite-v1:0",
        expected_prompt_version="v6",
    )
    return passed, {check["check"]: check["passed"] for check in checks}


def test_explicit_deterministic_safety_evidence_can_replace_model_execution(
    deterministic_safety_case,
):
    response, expected = deterministic_safety_case
    # Every expected prefix must match; exact equality is not required.
    expected["policy_finding_prefixes"].append("policy_evidence:")
    response["agent_results"][0]["policy_notes"].append("policy_evidence:insufficient")

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is True
    assert checks[EXECUTION_CHECK] is True
    assert "model_calls_recorded" not in checks
    assert (
        checks["model_provider"] and checks["model_id"] and checks["prompt_set_version"]
    )
    assert response["audit"]["model_calls"] == []
    assert response["audit"]["model_call_count"] == 0


@pytest.mark.parametrize(
    "field",
    [
        "model_calls",
        "model_call_count",
        "model_provider",
        "model_id",
        "prompt_set_version",
    ],
)
def test_deterministic_safety_rejects_missing_telemetry(
    deterministic_safety_case, field
):
    response, expected = deterministic_safety_case
    response["audit"].pop(field)

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    if field in {"model_calls", "model_call_count"}:
        assert checks[EXECUTION_CHECK] is False
    else:
        assert checks[field] is False


@pytest.mark.parametrize("count", [None, False, 0.0, "0", -1, 1])
def test_deterministic_safety_requires_explicit_integer_zero(
    deterministic_safety_case, count
):
    response, expected = deterministic_safety_case
    response["audit"]["model_call_count"] = count

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is False


@pytest.mark.parametrize("calls", [None, {}, (), ""])
def test_deterministic_safety_requires_explicit_empty_call_list(
    deterministic_safety_case, calls
):
    response, expected = deterministic_safety_case
    response["audit"]["model_calls"] = calls

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is False


@pytest.mark.parametrize(
    "prefixes,findings",
    [
        ([], ["regulated_advice:forbidden"]),
        (["regulated_advice:"], []),
        (["regulated_advice:"], ["unrelated_finding"]),
        (["regulated_advice:", "policy_evidence:"], ["regulated_advice:forbidden"]),
        ([""], ["unrelated_finding"]),
    ],
    ids=[
        "empty-rubric",
        "missing-finding",
        "wrong-finding",
        "partial-match",
        "empty-prefix",
    ],
)
def test_deterministic_safety_requires_all_nonempty_policy_prefixes(
    deterministic_safety_case,
    prefixes,
    findings,
):
    response, expected = deterministic_safety_case
    expected["policy_finding_prefixes"] = prefixes
    response["agent_results"][0]["policy_notes"] = findings

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is False


def test_deterministic_safety_rejects_absent_expected_policy_findings(
    deterministic_safety_case,
):
    response, expected = deterministic_safety_case
    expected.pop("policy_finding_prefixes")

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is False


@pytest.mark.parametrize(
    "expected_blocked,actual_blocked",
    [
        (False, False),
        (False, True),
        (True, False),
        (1, True),
        (True, 1),
    ],
    ids=[
        "normal-answer",
        "unexpected-block",
        "not-blocked",
        "expected-not-boolean",
        "actual-not-boolean",
    ],
)
def test_zero_calls_require_explicit_expected_and_actual_safety_block(
    deterministic_safety_case,
    expected_blocked,
    actual_blocked,
):
    response, expected = deterministic_safety_case
    expected["blocked"] = expected_blocked
    response["blocked"] = actual_blocked

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is False


def test_zero_calls_do_not_pass_without_expected_block_status(
    deterministic_safety_case,
):
    response, expected = deterministic_safety_case
    expected.pop("blocked")

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is False


@pytest.mark.parametrize("field", ["model_provider", "model_id", "prompt_set_version"])
def test_deterministic_safety_does_not_relax_model_or_prompt_identity(
    deterministic_safety_case,
    field,
):
    response, expected = deterministic_safety_case
    response["audit"][field] = "unexpected-value"

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is True
    assert checks[field] is False


@pytest.mark.parametrize("failed_check", ["minimum_disclaimers", "minimum_model_calls"])
def test_deterministic_safety_keeps_other_expectations(
    deterministic_safety_case, failed_check
):
    response, expected = deterministic_safety_case
    if failed_check == "minimum_disclaimers":
        response["disclaimers"] = []
    else:
        expected["minimum_model_calls"] = 1

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is False
    assert checks[EXECUTION_CHECK] is True
    assert checks[failed_check] is False


def test_recorded_model_execution_still_passes_without_deterministic_block_evidence(
    deterministic_safety_case,
):
    response, expected = deterministic_safety_case
    expected["blocked"] = response["blocked"] = False
    expected.pop("policy_finding_prefixes")
    response["agent_results"][0]["policy_notes"] = []
    response["audit"].update(
        model_calls=[{"component": "synthesizer"}], model_call_count=1
    )

    passed, checks = evaluate_safety_case(response, expected)

    assert passed is True
    assert checks[EXECUTION_CHECK] is True


def test_thresholds_report_quality_latency_and_cost_failures() -> None:
    report = {
        "pass_rate": 0.8,
        "latency_ms": {"p95": 9000},
        "cost_estimate": {"estimated_total": 1.5},
    }

    failures = enforce_thresholds(
        report,
        minimum_pass_rate=1.0,
        maximum_p95_ms=8000,
        maximum_estimated_cost_usd=1.0,
    )

    assert len(failures) == 3


def test_live_report_excludes_content_and_requires_cleanup(monkeypatch) -> None:
    response = {
        "blocked": False,
        "selected_agents": ["budget"],
        "answer": "Content that must not enter evidence",
        "agent_results": [],
        "sources": [],
        "audit": {
            "trace_id": "trace-1",
            "model_provider": "bedrock",
            "model_id": "model",
            "prompt_set_version": "v3",
            "model_call_count": 1,
            "model_input_tokens": 10,
            "model_output_tokens": 5,
            "model_calls": [{"component": "router"}],
        },
    }
    monkeypatch.setattr(
        live_evaluation,
        "request_json",
        lambda *_args, **_kwargs: (response, "correlation-1"),
    )
    monkeypatch.setattr(
        live_evaluation,
        "cleanup_session",
        lambda *_args, **_kwargs: False,
    )

    report = run_live_evaluation(
        url="https://example.test/api/coach",
        api_key="secret",
        cases=[
            {
                "id": "budget",
                "category": "routing",
                "request": {
                    "message": "Private synthetic prompt",
                    "snapshot": {"monthly_income": {"amount": 4000}},
                },
                "expected": {"selected_agents": ["budget"]},
            }
        ],
        repeats=1,
        timeout_seconds=1,
        expected_model_provider="bedrock",
        expected_model_id="model",
        expected_prompt_version="v3",
        input_cost_per_million=0.06,
        output_cost_per_million=0.24,
        commit_sha="abc123",
    )

    serialized = str(report)
    assert report["pass_rate"] == 0
    assert report["records"][0]["cleanup_succeeded"] is False
    assert "Private synthetic prompt" not in serialized
    assert "Content that must not enter evidence" not in serialized
    assert "secret" not in serialized


def test_live_report_retains_bounded_http_failure_diagnostics(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise LiveEndpointError(503, "correlation-503")

    monkeypatch.setattr(live_evaluation, "request_json", unavailable)
    monkeypatch.setattr(
        live_evaluation,
        "cleanup_session",
        lambda *_args, **_kwargs: True,
    )

    report = run_live_evaluation(
        url="https://example.test/api/coach",
        api_key="secret",
        cases=[
            {
                "id": "unavailable",
                "category": "routing",
                "request": {"message": "Private synthetic prompt"},
                "expected": {"selected_agents": ["budget"]},
            }
        ],
        repeats=1,
        timeout_seconds=1,
        expected_model_provider="bedrock",
        expected_model_id="model",
        expected_prompt_version="v4",
        input_cost_per_million=0.06,
        output_cost_per_million=0.24,
        commit_sha="abc123",
    )

    record = report["records"][0]
    assert record["passed"] is False
    assert record["error_type"] == "LiveEndpointError"
    assert record["http_status"] == 503
    assert record["correlation_id"] == "correlation-503"
    assert "Private synthetic prompt" not in str(report)
    assert "secret" not in str(report)


@pytest.mark.parametrize("fault", [None, "missing", "category", "gross", "date"])
def test_budget_acceptance_checks_extraction_and_missing_inputs(fault):
    draft = {
        "period_start": None,
        "planning": {"income_basis": "gross"},
        "categories": [{"category": "Pet Care", "limit_amount": 120}],
    }
    if fault == "category":
        draft["categories"][0]["limit_amount"] = 150
    if fault == "gross":
        draft["planning"]["income_basis"] = "take_home"
    if fault == "date":
        draft["period_start"] = "2026-10-01"
    response = {
        "agent_results": []
        if fault == "missing"
        else [{"agent": "budget", "data": {"budget_draft": draft}}]
    }
    _passed, checks = evaluate_response(
        response,
        {
            "budget_draft": {"period_start": None, "planning.income_basis": "gross"},
            "budget_categories": {"pet care": 120},
        },
        expected_model_provider="openai",
        expected_model_id="gpt-6-luna",
        expected_prompt_version="v6",
    )
    budget_checks = [item for item in checks if item["check"].startswith("budget_")]
    assert all(item["passed"] for item in budget_checks) is (fault is None)


def conversation_run(monkeypatch, request, cases, provider="openai", cleanup=None, **options):
    monkeypatch.setattr(live_evaluation, "request_json", request)
    monkeypatch.setattr(live_evaluation, "cleanup_session", cleanup or (lambda *_args: True))
    return run_live_evaluation(
        url="https://example.test/api/coach", api_key="private-api-key", cases=cases,
        repeats=1, timeout_seconds=1, expected_model_provider=provider,
        expected_model_id="model", expected_prompt_version="v6",
        input_cost_per_million=1, output_cost_per_million=2, commit_sha="abc123",
        **options,
    )


def turn_response(answer="Synthetic answer", *, blocked=False, input_tokens=10):
    return {
        "answer": answer, "blocked": blocked, "agent_results": [],
        "audit": {"model_provider": "openai", "model_id": "model", "prompt_set_version": "v6",
            "model_calls": [{"component": "router", "input_tokens": input_tokens, "output_tokens": 5}], "model_call_count": 1,
            "model_input_tokens": input_tokens, "model_output_tokens": 5},
    }


def test_request_latency_measures_each_turn_and_excludes_fixture_and_cleanup(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(live_evaluation.time, "perf_counter", lambda: clock[0])

    def request(*_args):
        clock[0] += 2
        return turn_response(), "correlation"

    def cleanup(*_args):
        clock[0] += 100
        return True

    report = conversation_run(monkeypatch, request, [{
        "id": "three-turns", "category": "continuity",
        "setup_turns": [{"message": "Setup one"}, {"message": "Setup two"}],
        "request": {"message": "Final question"}, "expected": {"blocked": False},
    }], cleanup=cleanup, latency_measurement="request")
    assert report["latency_unit"] == "coach_request"
    assert report["measured_requests"] == 3
    assert report["latency_ms"]["p95"] == 2000
    assert report["conversation_latency_ms"]["p95"] == 6000
    assert report["records"][0]["latency_ms"] == 6000


def test_failed_request_is_included_in_request_latency(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(live_evaluation.time, "perf_counter", lambda: clock[0])

    def request(*_args):
        clock[0] += 120
        raise TimeoutError()

    report = conversation_run(monkeypatch, request, [{
        "id": "timeout", "category": "availability",
        "request": {"message": "Synthetic question"}, "expected": {},
    }], latency_measurement="request")
    assert report["latency_ms"]["p95"] == 120000
    assert report["measured_requests"] == 1
    assert report["pass_rate"] == 0
    assert report["token_usage_complete"] is False


def test_multi_turn_live_evaluation_preserves_session_and_counts_every_turn(monkeypatch):
    sent = []
    cleanups = []

    def request(_url, _key, payload, _timeout):
        sent.append(payload)
        return turn_response("Private model answer", input_tokens=10 * len(sent)), "correlation"

    report = conversation_run(monkeypatch, request, [{
        "id": "reference", "category": "continuity", "rubric": ["Resolve the reference"],
        "setup_turns": [{"message": "Private setup turn"}, {"message": "Private second turn"}],
        "request": {"message": "Private final turn", "session_id": "untrusted", "user_id": "other"},
        "expected": {"blocked": False},
    }], cleanup=lambda *args: cleanups.append(args) or True)
    assert len(sent) == 3
    assert len({payload["session_id"] for payload in sent}) == 1
    assert len({payload["user_id"] for payload in sent}) == 1
    assert live_evaluation.SYNTHETIC_USER_PATTERN.fullmatch(sent[0]["user_id"])
    assert sent[0]["session_id"] != "untrusted"
    assert len(cleanups) == 1
    assert cleanups[0][2:4] == (sent[0]["user_id"], sent[0]["session_id"])
    assert report["records"][0]["model_call_count"] == 3
    assert report["token_usage"] == {"input": 60, "output": 15, "total": 75}
    assert report["cost_estimate"]["estimated_total"] == 0.00009
    assert report["records"][0]["setup_turn_count"] == 2
    assert report["measurement"] == "live_generated_contract_checks"
    assert report["semantic_quality_review"] == "required"
    assert "Private" not in json.dumps(report)
    assert "private-api-key" not in json.dumps(report)


def test_cases_seed_owned_records_in_isolation_and_delete_complete_user_data(monkeypatch):
    actors, created, sent, deleted = {}, [], [], []
    def owned(url, _key, method, payload, _timeout):
        if url.endswith("/profiles"):
            actor = payload["user_id"]
            assert actor not in actors
            actors[actor] = {"profile": payload, "transactions": [], "goals": []}
            created.append(actor)
            return payload
        actor = url.split("/users/")[1].split("/")[0]
        collection = url.rsplit("/", 1)[1]
        if collection in {"transactions", "goals"}:
            actors[actor][collection].append(payload.copy())
            return {"id": "seed-record"}
        if collection == "data-lifecycle":
            assert method == "GET"
            return {"policy_version": "reviewed-policy"}
        assert collection == "data" and method == "DELETE"
        assert payload == {"confirm_user_id": actor, "policy_version": "reviewed-policy"}
        deleted.append(actor)
        del actors[actor]
        return {"completed_at": "now"}
    def request(_url, _key, payload, _timeout):
        sent.append(payload)
        state = actors[payload["user_id"]]
        income = state["profile"]["monthly_income"]["amount"]
        assert len(state["transactions"]) == 1 and len(state["goals"]) == 1
        return turn_response(str(income)), None
    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", owned)
    cases = [{"id": str(income), "category": "isolated", "setup_turns": [{"message": "Setup"}],
        "request": {"message": "Final", "snapshot": {"monthly_income": {"amount": income},
            "preferences": {"preferred_language": "English"},
            "recent_transactions": [{"description": "Meal", "category": "food", "amount": {"amount": 10}, "occurred_on": "2026-09-01"}],
            "goals": [{"name": "Reserve", "target_amount": {"amount": 100}, "target_months": 2}]}},
        "expected": {"answer_contains": [str(income)]}} for income in (4000, 1000)]
    report = conversation_run(monkeypatch, request, cases)
    assert report["passed_runs"] == 2 and not actors
    assert len(set(created)) == 2 and deleted == created
    assert sent[0]["user_id"] == sent[1]["user_id"] != sent[2]["user_id"] == sent[3]["user_id"]
    assert all(live_evaluation.SYNTHETIC_USER_PATTERN.fullmatch(actor) for actor in created)
    assert all(record["cleanup_succeeded"] for record in report["records"])


def test_overlapping_snapshot_views_preserve_duplicate_records_without_duplicate_seeding():
    item = {"description": "Meal", "category": "food", "amount": {"amount": 10}, "occurred_on": "2026-09-01"}
    _, records, _ = live_evaluation._fixture_payloads({"recent_transactions": [item, item],
        "historical_transactions": [item, item], "recurring_expenses": [item]})
    assert len(records) == 2 and sum(record.get("recurring", False) for record in records) == 1


def test_fixture_limits_are_validated_before_any_owned_writes(monkeypatch):
    calls = []
    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="at most 200"):
        live_evaluation.seed_case_snapshot("https://example.test/api/coach", "key", "live-evaluation-" + "a" * 32,
                                          {"recent_transactions": [{}] * 201}, 1)
    assert not calls


@pytest.mark.parametrize("budgets", [
    {}, [{}], [{"period_start": "2026-08-01", "user_id": "real-user"}],
    [{"period_start": "2026-08-01"}] * 13,
    [{"period_start": "2026-08-01", "categories": [{"category": "x" * 100_001}]}],
])
def test_budget_fixture_limits_are_validated_before_any_owned_writes(monkeypatch, budgets):
    calls = []
    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="fixture budgets"):
        live_evaluation.seed_case_snapshot(
            "https://example.test/api/coach", "key", "live-evaluation-" + "a" * 32,
            {}, 1, budgets=budgets,
        )
    assert not calls


@pytest.mark.parametrize("coach_fails", [False, True])
def test_budget_fixture_uses_owned_api_and_is_cleaned_without_entering_evidence(monkeypatch, coach_fails):
    writes, sent, deleted = [], [], []
    budget = {"period_start": "2026-08-01", "currency": "SGD",
              "categories": [{"category": "Private synthetic category", "limit_amount": 123}],
              "planning": {"take_home_income": 5000, "savings_target": 1000, "expenses_confirmed": True}}

    def owned(url, _key, method, payload, _timeout):
        if method in {"POST", "PUT"}:
            writes.append((url, method, payload))
        if url.endswith("/data-lifecycle"):
            return {"policy_version": "reviewed-policy"}
        if method == "DELETE":
            deleted.append(payload["confirm_user_id"])
        return {}

    def request(_url, _key, payload, _timeout):
        sent.append(payload)
        if coach_fails:
            raise LiveEndpointError(503, "synthetic-failure")
        return turn_response(), None

    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", owned)
    report = conversation_run(monkeypatch, request, [{
        "id": "confirmed-budget", "category": "fixtures", "fixture_budgets": [budget],
        "request": {"message": "Assess the confirmed budget", "budget_period_start": "2026-08-01"},
        "expected": {"blocked": False},
    }])
    actor = sent[0]["user_id"]
    assert writes[-1] == (f"https://example.test/api/users/{actor}/budget", "PUT", budget)
    assert live_evaluation.SYNTHETIC_USER_PATTERN.fullmatch(actor)
    assert deleted == [actor]
    assert "fixture_budgets" not in sent[0] and "snapshot" not in sent[0]
    assert report["records"][0]["seeded_records"]["budgets"] == 1
    assert report["records"][0]["cleanup_succeeded"]
    assert report["passed_runs"] == (0 if coach_fails else 1)
    assert "Private synthetic category" not in json.dumps(report)
    assert "private-api-key" not in json.dumps(report)


@pytest.mark.parametrize("component,allowed", [
    ("router", True), ("goal_input_requirements", True), ("risk_compliance", True),
    ("goal_strategy", False), (None, False),
])
def test_missing_input_component_allowlist_rejects_paid_goal_execution(component, allowed):
    response = turn_response()
    response["audit"]["model_calls"][0]["component"] = component
    passed, checks = evaluate_response(
        response, {"maximum_model_calls": 3,
                   "allowed_model_components": ["router", "goal_input_requirements", "risk_compliance"]},
        expected_model_provider="openai", expected_model_id="model", expected_prompt_version="v6",
    )
    assert passed is allowed
    assert next(check["passed"] for check in checks if check["check"] == "allowed_model_components") is allowed


@pytest.mark.parametrize("rendered_citations", [False, True])
@pytest.mark.parametrize("status", ["grounded", "hybrid"])
@pytest.mark.parametrize("fault", [
    None, "partial_source", "unverified", "unsupported_question", "missing_question",
    "missing_quote", "fabricated_quote", "unapproved_source", "missing_sections",
    "model_only", "unlabelled_model", "source_claim_in_model", "model_link", "overlapping_sections", "unscoped_text",
])
def test_education_requires_verified_quote_coverage_and_separate_model_provenance(status, fault, rendered_citations):
    quote = "Diversification spreads investment risk."
    summary = quote + " [source:approved]"
    sections = [{"provenance": "retrieved", "start": 0, "end": len(summary)}]
    if status == "hybrid":
        start = len(summary) + 2
        summary += "\n\nModel knowledge (not verified against retrieved sources):\nA stable concept explanation."
        sections.append({"provenance": "model_knowledge", "start": start, "end": len(summary)})
    response = turn_response(summary)
    response["sources"] = [{"source_id": "approved"}]
    data = {"evidence_status": status, "sourced_evidence_status": "grounded",
            "coverage_assessment": "model_semantic_with_exact_quotes", "source_unanswered_topics": [],
            "sources": [{"source_id": "approved", "title": "Managing [investment] risk",
                         "canonical_url": "https://example.test/investment-risk/"}],
            "contexts": [{"source_id": "approved", "text": quote}],
            "subquestions": [{"question_id": "q1"}],
            "subquestion_coverage": [{"question_id": "q1", "status": "supported", "supporting_passages": [
                {"source_id": "approved", "quote": quote, "evidence_field": "text"}]}],
            "review_sections": sections}
    response["agent_results"] = [{"agent": "investment_education", "summary": summary, "data": data}]
    if fault == "partial_source":
        data["sourced_evidence_status"] = "partial"
    elif fault == "unverified":
        data["coverage_assessment"] = "semantic_contract_unverified"
    elif fault == "unsupported_question":
        data["subquestion_coverage"][0]["status"] = "unsupported"
    elif fault == "missing_question":
        data["subquestions"] = []
    elif fault in {"missing_quote", "fabricated_quote"}:
        data["subquestion_coverage"][0]["supporting_passages"][0]["quote"] = "" if fault == "missing_quote" else "An invented fact."
    elif fault == "unapproved_source":
        data["subquestion_coverage"][0]["supporting_passages"][0]["source_id"] = "unapproved"
    elif fault == "missing_sections":
        data["review_sections"] = []
    elif fault == "model_only":
        data["evidence_status"] = "general_knowledge"
    elif fault == "unscoped_text":
        response["answer"] = response["agent_results"][0]["summary"] = summary + "\nUnscoped assertion."
    elif fault in {"unlabelled_model", "source_claim_in_model", "model_link", "overlapping_sections"}:
        if status == "grounded":
            # A grounded answer cannot hide model-only material in its source scope.
            data["evidence_status"] = "hybrid"
        else:
            if fault == "unlabelled_model":
                summary = summary.replace("Model knowledge (not verified against retrieved sources):", "Unlabelled explanation:")
            elif fault == "source_claim_in_model":
                summary += " [source:approved]"
            elif fault == "model_link":
                summary += " https://example.test"
            else:
                sections[1]["start"] = 1
            sections[1]["end"] = len(summary)
            response["answer"] = response["agent_results"][0]["summary"] = summary
    if rendered_citations:
        for owner, key in ((response, "answer"), (response["agent_results"][0], "summary")):
            owner[key] = owner[key].replace(
                "[source:approved]", r"[Managing \[investment\] risk](https://example.test/investment-risk/)",
            )
    passed, _checks = evaluate_response(
        response, {"education_grounding_contract": True}, expected_model_provider="openai",
        expected_model_id="model", expected_prompt_version="v6",
    )
    assert passed is (fault is None)


def test_complete_user_cleanup_refuses_non_generated_identifiers(monkeypatch):
    calls = []
    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", lambda *args: calls.append(args))
    assert not live_evaluation.cleanup_user_data("https://example.test/api/coach", "key", "live-evaluation", 1)
    assert not live_evaluation.cleanup_user_data("https://example.test/api/coach", "key", "real-user", 1)
    assert not calls


def test_partial_fixture_seed_failure_cleans_generated_user_and_stops_coach(monkeypatch):
    deleted, coach_calls = [], []
    def owned(url, _key, method, payload, _timeout):
        if url.endswith("/transactions"):
            raise LiveEndpointError(422, "seed-failure")
        if url.endswith("/data-lifecycle"):
            return {"policy_version": "reviewed-policy"}
        if method == "DELETE":
            deleted.append(payload["confirm_user_id"])
        return {}
    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", owned)
    report = conversation_run(monkeypatch, lambda *args: coach_calls.append(args), [{
        "id": "seed-failure", "category": "fixtures", "request": {"message": "Never sent", "snapshot": {
            "recent_transactions": [{"description": "Meal", "category": "food", "amount": {"amount": 10}, "occurred_on": "2026-09-01"}]}}}])
    assert not coach_calls and len(deleted) == 1
    assert report["passed_runs"] == 0 and report["records"][0]["cleanup_succeeded"]
    assert report["records"][0]["http_status"] == 422
    assert report["records"][0]["failure_stage"] == "fixture_setup"
    assert report["fixture_stopped"] and not report["completed_requested_runs"]
    assert report["token_usage_complete"] and not report["usage_unknown"]
    assert report["records"][0]["usage_failure_codes"] == []


def test_invalid_setup_stops_final_request_and_still_counts_usage_and_cleanup(monkeypatch):
    sent = []
    cleanup_calls = []

    def request(_url, _key, payload, _timeout):
        sent.append(payload)
        return turn_response(blocked=True), None

    monkeypatch.setattr(live_evaluation, "request_json", request)
    monkeypatch.setattr(live_evaluation, "cleanup_session", lambda *args: cleanup_calls.append(args) or True)
    report = run_live_evaluation(
        url="https://example.test/api/coach", api_key="key",
        cases=[{"id": "failed-setup", "category": "continuity",
            "setup_turns": [{"message": "Setup"}], "request": {"message": "Do not send this"},
            "expected": {"blocked": False}}],
        repeats=1, timeout_seconds=1, expected_model_provider="openai", expected_model_id="model",
        expected_prompt_version="v6", input_cost_per_million=1, output_cost_per_million=2, commit_sha="abc123",
    )
    assert len(sent) == len(cleanup_calls) == 1
    assert cleanup_calls[0][2:4] == (sent[0]["user_id"], sent[0]["session_id"])
    assert report["passed_runs"] == 0
    assert report["token_usage"]["total"] == 15
    assert {check["check"] for check in report["records"][0]["checks"] if not check["passed"]} == {"setup[0].blocked"}


def test_setup_token_usage_survives_final_http_failure(monkeypatch):
    calls = []

    def request(_url, _key, payload, _timeout):
        calls.append(payload)
        if len(calls) == 2:
            raise LiveEndpointError(503, "final-failure")
        return turn_response(), "setup-correlation"

    report = conversation_run(monkeypatch, request, [{"id": "failure", "category": "continuity",
        "setup_turns": [{"message": "Setup"}], "request": {"message": "Final"}}])
    assert report["token_usage"]["total"] == 15
    assert report["records"][0]["cleanup_succeeded"] is True
    assert report["records"][0]["http_status"] == 503
    assert report["records"][0]["correlation_id"] == "final-failure"
    assert report["token_usage_complete"] is False


def test_oversized_setup_is_rejected_before_endpoint_call(monkeypatch):
    calls = []
    with pytest.raises(ValueError, match="at most six"):
        conversation_run(monkeypatch, lambda *args: calls.append(args), [{
            "id": "too-many", "category": "continuity", "setup_turns": [{"message": "Setup"}] * 7,
            "request": {"message": "Final"},
        }])
    assert calls == []


@pytest.mark.parametrize("expected,answer,data", [
    ({"answer_excludes": ["automatically saved"]}, "It was automatically saved", {}),
    ({"maximum_answer_words": 3}, "This has too many words", {}),
    ({"answer_language": "Chinese"}, "An English answer only", {}),
    ({"no_draft": True}, "A proposal", {"budget_draft": {"action": "set"}}),
])
def test_conversational_expectations_are_enforced(expected, answer, data):
    response = turn_response(answer)
    response["agent_results"] = [{"agent": "budget", "data": data}]
    passed, checks = evaluate_response(response, expected, expected_model_provider="openai",
        expected_model_id="model", expected_prompt_version="v6")
    assert not passed
    assert any(not check["passed"] for check in checks)


def test_conversational_dataset_contains_bounded_turns_and_review_rubrics():
    from pathlib import Path
    cases = live_evaluation.load_cases(Path(__file__).resolve().parents[2] / "llmsecops/conversational-live-evaluation-cases.jsonl")
    assert len(cases) >= 16
    assert all(case["expected"] and case["rubric"] for case in cases)
    assert sum(bool(case.get("setup_turns")) for case in cases) >= 4
    assert all(case["expected"].get("minimum_model_calls", 0) >= 1 for case in cases if case["expected"]["blocked"] is False)


def test_live_model_call_requirement_rejects_missing_provider_telemetry():
    passed, checks = evaluate_response(
        {"answer": "A canned response", "blocked": False},
        {"blocked": False, "minimum_model_calls": 1},
        expected_model_provider="openai", expected_model_id="model", expected_prompt_version="v6",
    )
    assert not passed
    failed = {check["check"] for check in checks if not check["passed"]}
    assert {"model_provider", "model_execution_or_deterministic_safety_evidence", "minimum_model_calls"}.issubset(failed)


@pytest.mark.parametrize("unknown_usage", [False, True])
def test_live_spend_cap_stops_future_calls_and_cleans_current_session(monkeypatch, unknown_usage):
    requests, cleanups = [], []
    def request(*args):
        requests.append(args)
        if unknown_usage:
            raise LiveEndpointError(503, "failed-call")
        return turn_response(), None
    monkeypatch.setattr(live_evaluation, "request_json", request)
    monkeypatch.setattr(live_evaluation, "cleanup_session", lambda *args: cleanups.append(args) or True)
    report = run_live_evaluation(
        url="https://example.test/api/coach", api_key="key",
        cases=[{"id": str(index), "category": "budget", "request": {"message": "Synthetic question"}}
               for index in range(2)], repeats=1, timeout_seconds=1,
        expected_model_provider="openai", expected_model_id="model", expected_prompt_version="v6",
        input_cost_per_million=1, output_cost_per_million=2, commit_sha="test",
        maximum_estimated_cost_usd=0.00002,
    )
    assert len(requests) == len(cleanups) == 1
    assert report["spending_stopped"] is True
    assert report["completed_requested_runs"] is False
    assert report["usage_unknown"] is unknown_usage
    assert any("all requested runs" in failure for failure in enforce_thresholds(report,
        minimum_pass_rate=0, maximum_p95_ms=1000, maximum_estimated_cost_usd=1))


@pytest.mark.parametrize("header,expected", [(str(UUID(int=100)), str(UUID(int=100))),
                                           ("../../private-token", None), (None, None)])
def test_http_failure_preserves_only_a_valid_trace_uuid(monkeypatch, header, expected):
    def unavailable(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test/api/coach", 503, "Private error",
                                     {"X-Correlation-ID": "correlation", "X-Trace-ID": header}, None)
    monkeypatch.setattr(live_evaluation.urllib.request, "urlopen", unavailable)
    with pytest.raises(LiveEndpointError) as failed:
        live_evaluation.request_json("https://example.test/api/coach", "private-key", {"message": "Private"}, 1)
    assert failed.value.trace_id == expected
    assert "private-token" not in str(failed.value)
    assert LiveEndpointError(503, None).trace_id is None


def failed_sdk_trace(trace_id, session_id, fault=None):
    events = []
    for index, (input_tokens, output_tokens) in enumerate(((100, 20), (200, 40))):
        call_id = str(UUID(int=index + 1))
        start = {"trace_id": trace_id, "event_type": "model.generation.started",
                 "details": {"call_id": call_id, "prompt": "Private prompt"}}
        finish = {"trace_id": trace_id, "event_type": "model.generation.finished", "details": {
            "call_id": call_id, "status": "completed", "input_tokens": input_tokens,
            "output_tokens": output_tokens, "answer": "Private answer", "error_code": None}}
        if index == 1:
            if fault == "provider_failed":
                finish["details"].update(status="failed", error_code="OPENAI_INVOCATION_FAILED")
            elif fault == "missing_usage":
                finish["details"]["output_tokens"] = None
            elif fault == "invalid_usage":
                finish["details"]["input_tokens"] = True
            elif fault == "other_trace_event":
                finish["trace_id"] = str(UUID(int=999))
            if fault != "missing_start":
                events.append(start)
            if fault != "missing_finish":
                events.append(finish)
            if fault == "conflicting_finish":
                events.append({**finish, "details": {**finish["details"], "output_tokens": 999}})
        else:
            events.extend((start, finish, finish))
    events.append({"trace_id": trace_id, "event_type": "workflow.failed",
                   "details": {"error_code": "MODEL_TOKEN_BUDGET_EXCEEDED", "error": "Private diagnostic"}})
    return {"trace_id": trace_id, "session_id": "other-chat" if fault == "other_session" else session_id,
            "status": "running" if fault == "running_trace" else "failed", "error_code": "AI_SERVICE_UNAVAILABLE",
            "audit": {"durable_events": events, "prompt": "Private prompt", "answer": "Private answer"}}


def failed_trace_run(monkeypatch, *, fault=None, cap=0.01):
    sent, lifecycle, ordering = [], [], []
    trace_id = str(UUID(int=100))

    def owned(url, key, method, payload, timeout):
        if "/coach/traces/" in url:
            ordering.append("trace_fetch")
            assert key == "private-key" and method == "GET" and payload is None
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            assert query == {"user_id": [sent[0]["user_id"]]}
            assert url.split("?")[0].endswith("/coach/traces/" + trace_id)
            if fault == "fetch_failed":
                raise OSError("Private fetch diagnostic")
            return {} if fault == "missing_trace" else failed_sdk_trace(trace_id, sent[0]["session_id"], fault)
        if url.endswith("/data-lifecycle"):
            return {"policy_version": "reviewed-policy"}
        if method == "DELETE":
            ordering.append("user_cleanup")
            lifecycle.append(payload["confirm_user_id"])
            assert payload["policy_version"] == "reviewed-policy"
        return {}

    def request(url, key, payload, timeout):
        sent.append(payload)
        if len(sent) == 1:
            raise LiveEndpointError(503, "failed-correlation", None if fault == "no_trace_header" else trace_id)
        return turn_response(), "next-correlation"

    def cleanup(*args):
        ordering.append("session_cleanup")
        return True

    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", owned)
    monkeypatch.setattr(live_evaluation, "request_json", request)
    monkeypatch.setattr(live_evaluation, "cleanup_session", cleanup)
    report = run_live_evaluation(
        url="https://example.test/api/coach", api_key="private-key",
        cases=[{"id": str(index), "category": "routing", "request": {"message": "Private request"}}
               for index in range(2)], repeats=1, timeout_seconds=1,
        expected_model_provider="openai", expected_model_id="model", expected_prompt_version="v6",
        input_cost_per_million=1, output_cost_per_million=2, commit_sha="test",
        maximum_estimated_cost_usd=cap,
    )
    assert lifecycle == [request["user_id"] for request in sent]
    assert all(live_evaluation.SYNTHETIC_USER_PATTERN.fullmatch(actor) for actor in lifecycle)
    assert len(set(lifecycle)) == len(lifecycle)
    assert "Private" not in json.dumps(report) and "private-key" not in json.dumps(report)
    assert "durable_events" not in json.dumps(report)
    return report, sent, ordering


@pytest.mark.parametrize("cap,continued", [(0.01, True), (0.0004, False)])
def test_failed_http_case_recovers_completed_sdk_usage_before_cleanup_and_obeys_cap(monkeypatch, cap, continued):
    report, sent, ordering = failed_trace_run(monkeypatch, cap=cap)
    first = report["records"][0]
    assert first["passed"] is False and first["http_status"] == 503
    assert first["input_tokens"] == 300 and first["output_tokens"] == 60
    assert first["model_call_count"] == first["recovered_completed_model_call_count"] == 2
    assert first["token_usage_complete"] is True
    assert first["error_code"] == "MODEL_TOKEN_BUDGET_EXCEEDED"
    assert first["turns"][0]["model_call_count"] == 2
    assert len(first["recovered_model_call_ids"]) == 2
    assert ordering.index("trace_fetch") < ordering.index("session_cleanup") < ordering.index("user_cleanup")
    assert report["usage_unknown"] is False
    assert report["spending_stopped"] is not continued
    assert report["token_usage"]["total"] == (375 if continued else 360)
    assert len(sent) == (2 if continued else 1)


@pytest.mark.parametrize("fault,known_input,known_output", [
    ("no_trace_header", 0, 0), ("fetch_failed", 0, 0), ("missing_trace", 0, 0), ("other_session", 0, 0),
    ("missing_finish", 100, 20), ("provider_failed", 100, 20), ("missing_usage", 100, 20),
    ("invalid_usage", 100, 20), ("other_trace_event", 100, 20), ("conflicting_finish", 100, 20),
    ("missing_start", 300, 60), ("running_trace", 300, 60),
])
def test_failed_usage_recovery_preserves_known_lower_bound_and_stops_on_unknown_calls(
    monkeypatch, fault, known_input, known_output,
):
    report, sent, _ = failed_trace_run(monkeypatch, fault=fault)
    assert len(sent) == 1
    assert report["spending_stopped"] is True and report["usage_unknown"] is True
    assert report["token_usage_complete"] is False
    assert report["token_usage"] == {"input": known_input, "output": known_output,
                                      "total": known_input + known_output}
    assert report["records"][0]["cleanup_succeeded"] is True


def test_failure_trace_lookup_never_uses_an_existing_user(monkeypatch):
    calls = []
    monkeypatch.setattr(live_evaluation, "_owned_api_request_json", lambda *args: calls.append(args))
    assert live_evaluation.failed_turn_usage("https://example.test/api/coach", "key", "real-user",
                                             "session", str(UUID(int=100)), 1) is None
    assert live_evaluation.failed_turn_usage("https://example.test/api/coach", "key", "live-evaluation-" + "a" * 32,
                                             "session", "../../private-token", 1) is None
    assert calls == []


@pytest.mark.parametrize("usage_complete", [False, True])
def test_composition_transport_unknown_usage_stops_even_when_backend_answer_has_known_prior_tokens(
    monkeypatch, usage_complete,
):
    sent, deleted = [], []

    def request(url, key, payload, timeout):
        sent.append(payload)
        response = turn_response("Validated backend preview")
        response["audit"].update(post_action_composed=False,
                                 composition_fallback_code="COMPOSITION_UNAVAILABLE" if not usage_complete
                                 else "ACTION_COMPOSITION_UNGROUNDED")
        if not usage_complete:
            response["audit"]["composition_usage_complete"] = False
        return response, "correlation"

    monkeypatch.setattr(live_evaluation, "request_json", request)
    monkeypatch.setattr(live_evaluation, "cleanup_session", lambda *args: deleted.append(args[2]) or True)
    report = run_live_evaluation(
        url="https://example.test/api/coach", api_key="private-key",
        cases=[{"id": str(i), "category": "action", "request": {"message": "Private synthetic preview"}}
               for i in range(2)], repeats=1, timeout_seconds=1,
        expected_model_provider="openai", expected_model_id="model", expected_prompt_version="v6",
        input_cost_per_million=1, output_cost_per_million=2, commit_sha="test",
        maximum_estimated_cost_usd=0.01,
    )
    assert len(sent) == len(deleted) == (2 if usage_complete else 1)
    assert report["token_usage"]["total"] == (30 if usage_complete else 15)
    assert report["token_usage_complete"] is usage_complete
    assert report["usage_unknown"] is not usage_complete
    assert report["spending_stopped"] is not usage_complete
    assert report["records"][0]["turns"][0]["token_usage_complete"] is usage_complete
    if not usage_complete:
        assert report["records"][0]["composition_usage_complete"] is False
        assert report["records"][0]["composition_fallback_code"] == "COMPOSITION_UNAVAILABLE"
        assert report["records"][0]["usage_failure_codes"] == ["COMPOSITION_USAGE_UNAVAILABLE"]
        assert any("account for model usage" in failure for failure in enforce_thresholds(
            report, minimum_pass_rate=0, maximum_p95_ms=1000, maximum_estimated_cost_usd=1))
    assert "Private" not in json.dumps(report)
