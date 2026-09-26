import copy
import io
import json
import urllib.error

import pytest

from infra.scripts import post_deploy_smoke


@pytest.fixture
def education_response():
    def source(source_id, corpus):
        return {
            "source_id": source_id, "title": "Approved education",
            "issuing_organization": "Synthetic authority",
            "canonical_url": "https://example.test/" + source_id,
            "published_at": "2026-01-01", "document_version": "2026-01-01",
            "checksum": "sha256:" + "a" * 64, "corpus_version": corpus,
            "review_due_at": "2026-12-01",
        }

    first = source("cited", "education-v1")
    second = source("retrieved-but-not-cited", "education-v1")
    fields = ("source_id", "document_version", "checksum", "corpus_version", "review_due_at")
    audit = {
        "trace_id": "synthetic-trace",
        "retrieval_corpus_versions": ["education-v1"],
        "retrieval_sources": [{key: item[key] for key in fields} for item in (first, second)],
        "policy_corpus_versions": ["policy-v1"],
        "policy_sources": [source("policy", "policy-v1")],
    }
    return {
        "blocked": False, "sources": [first], "audit": audit,
        "agent_results": [
            {"agent": "investment_education", "data": {
                "evidence_status": "grounded", "sources": [first, second],
            }},
            {"agent": "risk_compliance", "data": {"policy_evidence_status": "grounded"}},
        ],
    }


def run_education_smoke(monkeypatch, response, persisted_audit=None):
    replies = iter([
        (200, json.dumps(response)),
        (200, json.dumps({"audit": persisted_audit or response["audit"]})),
    ])
    monkeypatch.setattr(post_deploy_smoke, "request", lambda *args, **kwargs: next(replies))
    post_deploy_smoke.check_investment_education_rag(
        "https://example.test/api/coach", "synthetic-key", "education-v1", "policy-v1",
    )


def test_education_trace_retains_retrieved_sources_beyond_final_citations(
    monkeypatch, education_response,
):
    run_education_smoke(monkeypatch, education_response)


def test_education_smoke_accepts_multiple_chunks_from_one_approved_source(
    monkeypatch, education_response,
):
    retrieved = education_response["agent_results"][0]["data"]["sources"]
    retrieved.append(copy.deepcopy(retrieved[0]))
    run_education_smoke(monkeypatch, education_response)


def test_education_smoke_rejects_conflicting_chunks_from_one_source(
    monkeypatch, education_response,
):
    retrieved = education_response["agent_results"][0]["data"]["sources"]
    duplicate = copy.deepcopy(retrieved[0])
    duplicate["checksum"] = "sha256:" + "b" * 64
    retrieved.append(duplicate)
    with pytest.raises(AssertionError, match="conflicting source provenance"):
        run_education_smoke(monkeypatch, education_response)


@pytest.mark.parametrize("damage", ["missing_uncited", "wrong_id", "wrong_checksum", "duplicate", "missing_version"])
def test_education_smoke_rejects_incomplete_or_changed_retrieval_provenance(
    monkeypatch, education_response, damage,
):
    sources = education_response["audit"]["retrieval_sources"]
    if damage == "missing_uncited":
        sources.pop()
    elif damage == "wrong_id":
        sources[1]["source_id"] = "invented-source"
    elif damage == "wrong_checksum":
        sources[1]["checksum"] = "sha256:" + "b" * 64
    elif damage == "duplicate":
        sources.append(copy.deepcopy(sources[0]))
    else:
        del sources[1]["document_version"]
    with pytest.raises(AssertionError, match="provenance|retrieved|duplicate"):
        run_education_smoke(monkeypatch, education_response)


def test_education_smoke_rejects_citation_absent_from_retrieval(
    monkeypatch, education_response,
):
    education_response["sources"][0] = {**education_response["sources"][0], "source_id": "invented"}
    with pytest.raises(AssertionError, match="citation|retrieved"):
        run_education_smoke(monkeypatch, education_response)


@pytest.mark.parametrize("field", ["source_id", "document_version", "checksum", "corpus_version", "review_due_at"])
def test_education_smoke_verifies_persisted_retrieval_provenance(
    monkeypatch, education_response, field,
):
    persisted = copy.deepcopy(education_response["audit"])
    persisted["retrieval_sources"][1][field] = "changed"
    with pytest.raises(AssertionError, match="persisted.*provenance"):
        run_education_smoke(monkeypatch, education_response, persisted)


def test_request_reports_bounded_http_diagnostics(monkeypatch) -> None:
    http_error = urllib.error.HTTPError(
        "https://example.test/api/coach",
        503,
        "Service Unavailable",
        {"X-Correlation-ID": "trace-123"},
        io.BytesIO(
            b'{"detail":"The AI service is temporarily unable to generate a validated response."}'
        ),
    )

    def fail_request(*args, **kwargs):
        del args, kwargs
        raise http_error

    monkeypatch.setattr(urllib.request, "urlopen", fail_request)

    with pytest.raises(
        post_deploy_smoke.SmokeRequestError,
        match=(
            "HTTP 503; correlation_id=trace-123; "
            "detail=The AI service is temporarily unable"
        ),
    ):
        post_deploy_smoke.request(
            "https://example.test/api/coach",
            method="POST",
            body={"message": "synthetic smoke request"},
            api_key="not-printed",
        )


def test_request_omits_unstructured_error_body(monkeypatch) -> None:
    http_error = urllib.error.HTTPError(
        "https://example.test/api/coach",
        502,
        "Bad Gateway",
        {},
        io.BytesIO(b"upstream internal response that must not be copied"),
    )

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(http_error),
    )

    with pytest.raises(post_deploy_smoke.SmokeRequestError) as raised:
        post_deploy_smoke.request("https://example.test/health")

    assert "response detail unavailable" in str(raised.value)
    assert "upstream internal response" not in str(raised.value)


def test_authentication_smoke_requires_unauthenticated_401(monkeypatch) -> None:
    monkeypatch.setattr(
        post_deploy_smoke,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            post_deploy_smoke.SmokeRequestError(
                "HTTP 401; correlation_id=trace-auth; detail=Authentication is required."
            )
        ),
    )

    post_deploy_smoke.check_user_authentication_required(
        "https://example.test/api/coach"
    )


def test_authentication_smoke_rejects_success(monkeypatch) -> None:
    monkeypatch.setattr(
        post_deploy_smoke,
        "request",
        lambda *args, **kwargs: (200, '{"answer":"unsafe"}'),
    )

    with pytest.raises(AssertionError, match="was accepted"):
        post_deploy_smoke.check_user_authentication_required(
            "https://example.test/api/coach"
        )


def test_conditional_education_smoke_verifies_tool_trace(monkeypatch) -> None:
    corpus = "investment-education-sg@test-v1"
    audit = {
        "trace_id": "trace-conditional",
        "retrieval_consumers": ["budget"],
        "retrieval_corpus_versions": [corpus],
        "dependency_resolutions": [
            {
                "capability": "education_context",
                "resolution": "resolved",
            }
        ],
        "dependency_edges": [
            {
                "capability": "education_context",
                "provider_task_id": "tool:education_retriever:fingerprint",
            }
        ],
    }
    coach_response = {
        "blocked": False,
        "selected_agents": ["budget"],
        "agent_results": [
            {
                "agent": "budget",
                "data": {
                    "income": 4000,
                    "evidence_status": "grounded",
                    "contexts": [{"source_id": "approved-source"}],
                    "sources": [{"corpus_version": corpus}],
                },
            }
        ],
        "audit": audit,
    }
    responses = iter(
        [
            (200, json.dumps(coach_response)),
            (200, json.dumps({"audit": audit})),
        ]
    )
    calls = []

    def record_request(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(
        post_deploy_smoke,
        "request",
        record_request,
    )

    post_deploy_smoke.check_conditional_education_rag(
        "https://example.test/api/coach",
        "synthetic-api-key",
        corpus,
    )

    assert calls[0][1]["body"]["user_id"] == (
        "deployment-conditional-rag-smoke-test"
    )
    assert calls[0][1]["body"]["session_id"] == (
        "deployment-conditional-rag-smoke-test-v2"
    )
    assert calls[1][0][0].endswith(
        "?user_id=deployment-conditional-rag-smoke-test"
    )


def test_persistence_smoke_verifies_lifecycle_export_and_complete_cleanup(
    monkeypatch,
) -> None:
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(url, method="GET", body=None, api_key=None):
        del api_key
        calls.append((method, url, body))
        if url.endswith("/transactions") and method == "POST":
            return 201, '{"id":"transaction-1"}'
        if url.endswith("/snapshot"):
            return 200, json.dumps(
                {
                    "monthly_income": {"amount": 4100},
                    "recent_transactions": [
                        {"description": "Deployment smoke transaction"}
                    ],
                }
            )
        if "dashboard?" in url:
            return 200, json.dumps(
                {"transaction_count": 1, "budget": {"total_limit": 10}}
            )
        if url.endswith("/data-lifecycle"):
            return 200, json.dumps(
                {
                    "policy_version": "data-lifecycle-v1",
                    "retention": {
                        "chat_history_days": 90,
                        "orchestration_traces_days": 30,
                    },
                    "durable_memory": {"feature_enabled": False},
                }
            )
        if url.endswith("/data-export"):
            return 200, json.dumps(
                {
                    "policy_version": "data-lifecycle-v1",
                    "data": {
                        "profile": {"monthly_income": {"amount": 4100}},
                        "transactions": [{"id": "transaction-1"}],
                    },
                }
            )
        if url.endswith("/data") and method == "DELETE":
            return 200, json.dumps({"deleted_counts": {"profiles": 1}})
        return 200, "{}"

    monkeypatch.setattr(post_deploy_smoke, "request", fake_request)

    post_deploy_smoke.check_persistence(
        "https://example.test/api", "synthetic-api-key"
    )

    assert calls[-1] == (
        "DELETE",
        "https://example.test/api/users/deployment-smoke-test/data",
        {
            "confirm_user_id": "deployment-smoke-test",
            "policy_version": "data-lifecycle-v1",
        },
    )
