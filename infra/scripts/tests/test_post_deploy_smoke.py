import copy
import io
import json
import urllib.error
from datetime import date

import pytest

from infra.scripts import post_deploy_smoke

MODEL_SECTION_LABEL = (
    "AI model knowledge — no live web search "
    "(not verified against retrieved sources):\n\n"
)


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
        "blocked": False,
        "answer": (
            "RAG knowledge base (saved documents; no live web search):\n\n"
            "Approved material. [Approved education](https://example.test/cited)"
        ),
        "sources": [first], "audit": audit,
        "agent_results": [
            {"agent": "investment_education", "blocked": False, "data": {
                "evidence_status": "grounded", "sources": [first, second],
            }},
            {"agent": "risk_compliance", "blocked": False, "data": {
                "policy_evidence_status": "grounded", "request_allowed": True,
                "financial_language_safe": True, "answer_complete": True,
            }},
        ],
    }


@pytest.fixture
def hybrid_education_response(education_response):
    investment = education_response["agent_results"][0]["data"]
    investment["evidence_status"] = "hybrid"
    investment["general_knowledge"] = [
        {"topic": "diversification", "text": "General educational context."}
    ]
    education_response["answer"] += (
        f"\n\n{MODEL_SECTION_LABEL}Additional general context."
    )
    return education_response


def run_education_smoke(monkeypatch, response, persisted_audit=None):
    replies = iter([
        (200, json.dumps(response)),
        (200, json.dumps({"audit": persisted_audit or response["audit"]})),
    ])
    urls = []

    def record_request(url, **kwargs):
        urls.append(url)
        return next(replies)

    monkeypatch.setattr(post_deploy_smoke, "request", record_request)
    post_deploy_smoke.check_investment_education_rag(
        "https://example.test/api/coach", "synthetic-key", "education-v1", "policy-v1",
    )
    assert urls == [
        "https://example.test/api/coach",
        "https://example.test/api/coach/traces/synthetic-trace?user_id=deployment-smoke-test",
    ]


def test_education_trace_retains_retrieved_sources_beyond_final_citations(
    monkeypatch, education_response,
):
    run_education_smoke(monkeypatch, education_response)


def test_education_smoke_accepts_hybrid_investment_response(
    monkeypatch, hybrid_education_response,
):
    run_education_smoke(monkeypatch, hybrid_education_response)


def test_education_smoke_accepts_supported_table_without_forced_heading(monkeypatch, education_response):
    education_response["answer"] = (
        "| Concept | Explanation |\n|---|---|\n"
        "| Risk | Approved material. [Approved education](https://example.test/cited) |"
    )
    run_education_smoke(monkeypatch, education_response)


@pytest.mark.parametrize("status", ["general_knowledge", "insufficient", "unknown"])
def test_education_smoke_rejects_non_rag_investment_status(
    monkeypatch, education_response, status,
):
    education_response["agent_results"][0]["data"]["evidence_status"] = status

    with pytest.raises(AssertionError):
        run_education_smoke(monkeypatch, education_response)


@pytest.mark.parametrize(
    "damage",
    ["missing_list", "missing_label", "missing_body", "citation_moved", "model_section_citation"],
)
def test_education_smoke_rejects_incomplete_hybrid_sections(
    monkeypatch, hybrid_education_response, damage,
):
    investment = hybrid_education_response["agent_results"][0]["data"]
    answer = hybrid_education_response["answer"]
    rag_answer = answer.split(f"\n\n{MODEL_SECTION_LABEL}", 1)[0]
    if damage == "missing_list":
        investment["general_knowledge"] = []
    elif damage == "missing_label":
        hybrid_education_response["answer"] = rag_answer + "\n\nGeneral context."
    elif damage == "missing_body":
        hybrid_education_response["answer"] = rag_answer + f"\n\n{MODEL_SECTION_LABEL}"
    elif damage == "citation_moved":
        hybrid_education_response["answer"] = (
            "RAG knowledge base (saved documents; no live web search):\n\n"
            "Approved material.\n\n"
            f"{MODEL_SECTION_LABEL}General context. "
            "[Approved education](https://example.test/cited)"
        )
    else:
        hybrid_education_response["answer"] += (
            " [Other source](https://example.test/other)"
        )

    with pytest.raises(AssertionError):
        run_education_smoke(monkeypatch, hybrid_education_response)


@pytest.mark.parametrize(
    "damage", ["empty_answer", "blocked", "missing_rag_link"]
)
def test_education_smoke_rejects_incomplete_grounded_response(
    monkeypatch, education_response, damage,
):
    if damage == "empty_answer":
        education_response["answer"] = ""
    elif damage == "blocked":
        education_response["agent_results"][0]["blocked"] = True
    elif damage == "missing_rag_heading":
        education_response["answer"] = (
            "Saved documents:\n\nApproved material. "
            "[Approved education](https://example.test/cited)"
        )
    else:
        education_response["answer"] = (
            "RAG knowledge base (saved documents; no live web search):\n\n"
            "Approved material without a displayed link."
        )

    with pytest.raises(AssertionError):
        run_education_smoke(monkeypatch, education_response)


@pytest.mark.parametrize("damage", ["model_data", "model_section"])
def test_education_smoke_rejects_model_only_content_in_grounded_response(
    monkeypatch, education_response, damage,
):
    if damage == "model_data":
        education_response["agent_results"][0]["data"]["general_knowledge"] = [
            {"topic": "diversification", "text": "Unverified context."}
        ]
    else:
        education_response["answer"] += f"\n\n{MODEL_SECTION_LABEL}Unverified context."

    with pytest.raises(AssertionError):
        run_education_smoke(monkeypatch, education_response)


@pytest.mark.parametrize(
    "damage",
    ["blocked", "ungrounded", "disallowed", "unsafe", "incomplete"],
)
def test_education_smoke_requires_positive_compliance_result(
    monkeypatch, education_response, damage,
):
    compliance = education_response["agent_results"][1]
    if damage == "blocked":
        compliance["blocked"] = True
    elif damage == "ungrounded":
        compliance["data"]["policy_evidence_status"] = "insufficient"
    else:
        field = {
            "disallowed": "request_allowed",
            "unsafe": "financial_language_safe",
            "incomplete": "answer_complete",
        }[damage]
        compliance["data"][field] = False

    with pytest.raises(AssertionError):
        run_education_smoke(monkeypatch, education_response)


@pytest.mark.parametrize(
    ("damage", "failure"),
    [("retrieval_checksum", "provenance"), ("compliance", "safe and complete")],
)
def test_hybrid_smoke_still_requires_retrieval_provenance_and_compliance(
    monkeypatch, hybrid_education_response, damage, failure,
):
    if damage == "retrieval_checksum":
        hybrid_education_response["audit"]["retrieval_sources"][1]["checksum"] = (
            "sha256:" + "b" * 64
        )
    else:
        hybrid_education_response["agent_results"][1]["data"][
            "financial_language_safe"
        ] = False

    with pytest.raises(AssertionError, match=failure):
        run_education_smoke(monkeypatch, hybrid_education_response)


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
    monkeypatch.setattr(post_deploy_smoke, "_financial_today", lambda: date(2026, 11, 1))

    def fake_request(url, method="GET", body=None, api_key=None):
        del api_key
        calls.append((method, url, body))
        if url.endswith("/transactions") and method == "POST":
            return 201, '{"id":"transaction-1"}'
        if url.endswith("/snapshot"):
            return 200, json.dumps(
                {
                    "monthly_income": {"amount": 4100},
                    "period_start": "2026-11-01",
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

    transaction = next(body for method, url, body in calls if method == "POST" and url.endswith("/transactions"))
    budget = next(body for method, url, body in calls if method == "PUT" and url.endswith("/budget"))
    assert transaction["occurred_on"] == "2026-11-01"
    assert budget["period_start"] == "2026-11-01"
    assert any(url.endswith("/dashboard?period_start=2026-11-01") for _, url, _ in calls)

    assert calls[-1] == (
        "DELETE",
        "https://example.test/api/users/deployment-smoke-test/data",
        {
            "confirm_user_id": "deployment-smoke-test",
            "policy_version": "data-lifecycle-v1",
        },
    )
