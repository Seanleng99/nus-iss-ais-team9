from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.guardrails import sanitize_rag_document
from app.rag.policy import (
    BedrockPolicyRetriever,
    LocalPolicyRetriever,
    create_policy_retriever,
)
from app.rag.retriever import RetrievalError


def _metadata(**overrides) -> dict:
    metadata = {
        "source_id": "coach-advice-boundary-policy",
        "title": "Financial coaching advice boundary",
        "issuing_organization": "AI Financial Wellness Coach Governance",
        "canonical_url": "https://example.com/policy",
        "published_at": "2026-08-29",
        "ingested_at": "2026-08-29T00:00:00Z",
        "document_version": "2026-08-29",
        "checksum": "sha256:" + "a" * 64,
        "review_status": "approved",
        "corpus_version": "financial-coach-policy-sg@2026-08-29.1",
        "manifest_schema_version": 2,
        "review_due_at": "2099-12-31",
        "usage_scope": "synthetic_demo_only",
    }
    metadata.update(overrides)
    return metadata


class StubClient:
    def __init__(self, metadata: dict | None = None, *, score: float = 0.91) -> None:
        self.metadata = metadata or _metadata()
        self.score = score
        self.request: dict | None = None

    def retrieve(self, **kwargs) -> dict:
        self.request = kwargs
        return {
            "retrievalResults": [
                {
                    "content": {"text": "Block personalized product recommendations."},
                    "metadata": self.metadata,
                    "score": self.score,
                }
            ]
        }


def _retriever(client) -> BedrockPolicyRetriever:
    return BedrockPolicyRetriever(
        knowledge_base_id="POLICYKB12",
        aws_region="ap-southeast-1",
        expected_corpus_version="financial-coach-policy-sg@2026-08-29.1",
        minimum_score=0.6,
        client=client,
    )


def test_local_policy_retriever_returns_governed_provenance() -> None:
    results = LocalPolicyRetriever().retrieve("Create a monthly budget")

    assert results
    assert results[0].source_id == "coach-advice-boundary-policy"
    assert results[0].corpus_version == "financial-coach-policy-sg@local-fixture-v1"
    assert results[0].checksum.startswith("sha256:")


def test_reviewed_policy_documents_and_fixture_keep_usable_instruction_evidence():
    documents = Path(__file__).resolve().parents[3] / "knowledge/policy_controls/documents"
    paths = list(documents.glob("*.md"))
    assert len(paths) == 3
    for path in paths:
        assert not sanitize_rag_document(path.read_text()).findings, path.name
    policy = LocalPolicyRetriever().retrieve("instruction security")[0]
    assert policy.source_id == "coach-instruction-security-policy"
    assert not policy.findings
    assert "untrusted data" in policy.text


def test_bedrock_policy_retriever_maps_strict_approved_metadata() -> None:
    client = StubClient(
        _metadata(**{"x-amz-bedrock-kb-data-source-id": "DATASOURCE123"})
    )

    results = _retriever(client).retrieve("Review this budget", top_k=2)

    assert results[0].source_id == "coach-advice-boundary-policy"
    assert results[0].score == 0.91
    assert client.request == {
        "knowledgeBaseId": "POLICYKB12",
        "retrievalQuery": {"text": "Review this budget"},
        "retrievalConfiguration": {
            "vectorSearchConfiguration": {
                "numberOfResults": 2,
                "filter": {"andAll": [
                    {"equals": {"key": "corpus_version", "value": "financial-coach-policy-sg@2026-08-29.1"}},
                    {"equals": {"key": "review_status", "value": "approved"}},
                ]},
            }
        },
    }


@pytest.mark.parametrize(
    ("metadata", "score"),
    [
        (_metadata(review_status="pending"), 0.91),
        (_metadata(corpus_version="financial-coach-policy-sg@old"), 0.91),
        (_metadata(review_due_at="2026-01-01"), 0.91),
        (_metadata(unexpected_governance_field="reject-me"), 0.91),
        (_metadata(), 0.2),
    ],
)
def test_bedrock_policy_retriever_rejects_untrusted_or_weak_results(
    metadata: dict,
    score: float,
) -> None:
    assert _retriever(StubClient(metadata, score=score)).retrieve("Review") == []


def test_bedrock_policy_retriever_hides_provider_failure_details() -> None:
    class FailingClient:
        def retrieve(self, **kwargs) -> dict:
            del kwargs
            raise RuntimeError("sensitive provider detail")

    with pytest.raises(RetrievalError, match="policy knowledge base") as error:
        _retriever(FailingClient()).retrieve("Review")

    assert error.value.component == "policy_retriever"
    assert "sensitive provider detail" not in str(error.value)


@pytest.mark.parametrize("bad_item", [
    None,
    {"score": "not-a-number"},
    {"score": 0.9, "metadata": None, "content": {"text": "bad"}},
    {"score": float("nan"), "metadata": _metadata(), "content": {"text": "bad"}},
    {"score": float("inf"), "metadata": _metadata(), "content": {"text": "bad"}},
    {"score": 0.9, "metadata": _metadata(), "content": {"text": ""}},
    {"score": 0.9, "metadata": _metadata(), "content": {"text": None}},
])
def test_bad_policy_chunks_do_not_replace_or_hide_valid_evidence(bad_item):
    class MixedClient(StubClient):
        def retrieve(self, **kwargs):
            response = super().retrieve(**kwargs)
            response["retrievalResults"].insert(0, bad_item)
            return response

    results = _retriever(MixedClient()).retrieve("Review")
    assert len(results) == 1
    assert results[0].text == "Block personalized product recommendations."


def test_duplicate_policy_chunks_are_only_returned_once():
    class DuplicateClient(StubClient):
        def retrieve(self, **kwargs):
            response = super().retrieve(**kwargs)
            response["retrievalResults"] *= 2
            return response

    assert len(_retriever(DuplicateClient()).retrieve("Review")) == 1


def test_deployed_config_creates_bedrock_policy_retriever() -> None:
    config = Settings(
        APP_ENV="demo",
        AI_SERVICE_API_KEY="a-secure-demo-key-that-is-long-enough",
        MODEL_PROVIDER="bedrock",
        RAG_PROVIDER="bedrock",
        EDUCATION_KNOWLEDGE_BASE_ID="EDUCATION123",
        EDUCATION_CORPUS_VERSION="investment-education-sg@2026-08-28.1",
        POLICY_RAG_PROVIDER="bedrock",
        POLICY_KNOWLEDGE_BASE_ID="POLICYKB12",
        POLICY_CORPUS_VERSION="financial-coach-policy-sg@2026-08-29.1",
        POLICY_RAG_MINIMUM_SCORE=0.7,
    )

    retriever = create_policy_retriever(config)

    assert isinstance(retriever, BedrockPolicyRetriever)
    assert retriever.knowledge_base_id == "POLICYKB12"
    assert retriever.minimum_score == 0.7
