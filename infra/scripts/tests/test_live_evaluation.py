import urllib.error

from infra.scripts import live_evaluation
from infra.scripts.live_evaluation import (
    chat_session_delete_url,
    cleanup_session,
    enforce_thresholds,
    evaluate_response,
    run_live_evaluation,
)


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

    assert cleanup_session(
        "https://example.test/api/coach", "secret", "user", "session", 1
    ) is True


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
    response = {
        "blocked": False,
        "agent_results": [
            {
                "agent": "investment_education",
                "data": {"evidence_status": "grounded"},
            }
        ],
        "sources": [{"source_id": "approved-source"}],
        "audit": {
            "model_provider": "bedrock",
            "model_id": "model",
            "prompt_set_version": "v3",
            "model_calls": [{"component": "router"}],
        },
    }

    passed, _ = evaluate_response(
        response,
        {"minimum_sources": 1, "evidence_status": "grounded"},
        expected_model_provider="bedrock",
        expected_model_id="model",
        expected_prompt_version="v3",
    )

    assert passed is True


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
