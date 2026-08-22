import pytest

from app.core.config import Settings
from app.rag.retriever import (
    BedrockEducationRetriever,
    LocalEducationRetriever,
    RetrievalError,
    create_education_retriever,
)


def test_education_query_returns_relevant_approved_source_metadata() -> None:
    results = LocalEducationRetriever().retrieve(
        "Explain diversification and ETF risk for a beginner"
    )

    assert results
    assert results[0].source_id == "cpf-beginners-guide-to-investing"
    assert results[0].issuing_organization == "CPF Board"
    assert results[0].canonical_url == (
        "https://www.cpf.gov.sg/member/infohub/educational-resources/"
        "a-beginners-guide-to-investing-in-singapore"
    )
    assert results[0].published_at == "2026-05-07"
    assert results[0].score > 0


def test_cpfis_query_returns_the_specific_cpf_education_guide() -> None:
    results = LocalEducationRetriever().retrieve(
        "What should I understand about CPFIS risks and CPF investment savings?"
    )

    assert results[0].source_id == "cpf-investment-scheme-guide"
    assert "cpf-investment-scheme-what-you-need-to-know" in results[0].canonical_url


def test_bedrock_retriever_maps_approved_metadata() -> None:
    class StubKnowledgeBaseClient:
        def __init__(self) -> None:
            self.request: dict | None = None

        def retrieve(self, **kwargs) -> dict:
            self.request = kwargs
            return {
                "retrievalResults": [
                    {
                        "content": {"text": "Diversification can reduce concentration risk."},
                        "metadata": {
                            "source_id": "mas-diversification-guide",
                            "title": "Understanding diversification",
                            "issuing_organization": "MoneySense",
                            "canonical_url": "https://www.moneysense.gov.sg/example",
                            "published_at": "2026-07-02",
                            "review_status": "approved",
                        },
                        "score": 0.91,
                    }
                ]
            }

    client = StubKnowledgeBaseClient()
    retriever = BedrockEducationRetriever(
        knowledge_base_id="EDUCATION123",
        aws_region="ap-southeast-1",
        client=client,
    )

    results = retriever.retrieve("Explain diversification", top_k=2)

    assert results[0].source_id == "mas-diversification-guide"
    assert results[0].issuing_organization == "MoneySense"
    assert results[0].score == 0.91
    assert client.request == {
        "knowledgeBaseId": "EDUCATION123",
        "retrievalQuery": {"text": "Explain diversification"},
        "retrievalConfiguration": {
            "vectorSearchConfiguration": {"numberOfResults": 2}
        },
    }


def test_bedrock_retriever_excludes_weak_evidence() -> None:
    class WeakResultClient:
        def retrieve(self, **kwargs) -> dict:
            del kwargs
            return {
                "retrievalResults": [
                    {
                        "content": {"text": "Weakly related content."},
                        "metadata": {
                            "source_id": "weak-source",
                            "title": "Weak source",
                            "issuing_organization": "CPF Board",
                            "canonical_url": "https://www.cpf.gov.sg/example",
                            "published_at": "2026-05-07",
                            "review_status": "approved",
                        },
                        "score": 0.2,
                    }
                ]
            }

    retriever = BedrockEducationRetriever(
        knowledge_base_id="EDUCATION123",
        aws_region="ap-southeast-1",
        minimum_score=0.6,
        client=WeakResultClient(),
    )

    assert retriever.retrieve("Explain diversification") == []


def test_bedrock_retriever_excludes_unapproved_documents() -> None:
    class PendingReviewClient:
        def retrieve(self, **kwargs) -> dict:
            del kwargs
            return {
                "retrievalResults": [
                    {
                        "content": {"text": "Content awaiting review."},
                        "metadata": {
                            "source_id": "pending-source",
                            "title": "Pending source",
                            "issuing_organization": "CPF Board",
                            "canonical_url": "https://www.cpf.gov.sg/example",
                            "published_at": "2026-05-07",
                            "review_status": "pending",
                        },
                        "score": 0.9,
                    }
                ]
            }

    retriever = BedrockEducationRetriever(
        knowledge_base_id="EDUCATION123",
        aws_region="ap-southeast-1",
        client=PendingReviewClient(),
    )

    assert retriever.retrieve("Explain diversification") == []


def test_bedrock_retriever_hides_provider_failure_details() -> None:
    class FailingClient:
        def retrieve(self, **kwargs) -> dict:
            del kwargs
            raise RuntimeError("sensitive AWS provider detail")

    retriever = BedrockEducationRetriever(
        knowledge_base_id="EDUCATION123",
        aws_region="ap-southeast-1",
        client=FailingClient(),
    )

    with pytest.raises(RetrievalError, match="knowledge base") as error:
        retriever.retrieve("Explain diversification")

    assert "sensitive AWS provider detail" not in str(error.value)


def test_deployed_config_creates_bedrock_education_retriever() -> None:
    config = Settings(
        APP_ENV="demo",
        AI_SERVICE_API_KEY="a-secure-demo-key-that-is-long-enough",
        MODEL_PROVIDER="bedrock",
        RAG_PROVIDER="bedrock",
        EDUCATION_KNOWLEDGE_BASE_ID="EDUCATION123",
        RAG_MINIMUM_SCORE=0.7,
    )

    retriever = create_education_retriever(config)

    assert isinstance(retriever, BedrockEducationRetriever)
    assert retriever.knowledge_base_id == "EDUCATION123"
    assert retriever.minimum_score == 0.7
