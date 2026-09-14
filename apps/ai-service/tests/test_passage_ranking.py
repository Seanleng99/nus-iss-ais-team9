import pytest

from app.rag.ranking import passage_scores
from app.rag.retriever import BedrockEducationRetriever


def candidate(text, source_id, score=0.9):
    return {
        "content": {"text": text},
        "score": score,
        "metadata": {
            "source_id": source_id,
            "title": "Investment education",
            "issuing_organization": "MoneySense",
            "canonical_url": "https://www.moneysense.gov.sg/example",
            "published_at": "2026-07-02",
            "ingested_at": "2026-08-28T00:00:00Z",
            "document_version": "2026-07-02",
            "checksum": "sha256:" + "a" * 64,
            "review_status": "approved",
            "corpus_version": "investment-education-sg@2026-08-28.1",
            "manifest_schema_version": 2,
            "review_due_at": "2099-12-31",
            "usage_scope": "synthetic_demo_only",
        },
    }


def test_specific_passage_beyond_first_three_is_selected_without_lowering_score_gate():
    specific = "An ETF's traded price is subject to demand and supply and can differ from NAV."

    class Client:
        def retrieve(self, **kwargs):
            assert kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]["numberOfResults"] == 20
            return {"retrievalResults": [
                *[candidate("ETFs are investment funds traded on an exchange.", f"intro-{i}") for i in range(3)],
                candidate(specific, "price-guide", 0.75),
                candidate(specific * 5, "weak-evidence", 0.2),
            ]}

    retriever = BedrockEducationRetriever(
        knowledge_base_id="EDUCATION1", aws_region="ap-southeast-1",
        expected_corpus_version="investment-education-sg@2026-08-28.1",
        minimum_score=0.6, client=Client(),
    )
    result = retriever.retrieve("General investment education about ETF net asset value, traded price demand supply")
    assert len(result) == 3
    assert result[0].source_id == "price-guide"
    assert result[0].text == specific
    assert result[0].score == 0.75
    assert "weak-evidence" not in {item.source_id for item in result}


@pytest.mark.parametrize("top_k", [0, 21])
def test_managed_retrieval_rejects_unbounded_result_counts_before_aws_call(top_k):
    retriever = BedrockEducationRetriever(
        knowledge_base_id="EDUCATION1", aws_region="ap-southeast-1",
        expected_corpus_version="investment-education-sg@2026-08-28.1", client=object(),
    )
    with pytest.raises(ValueError, match="top_k"):
        retriever.retrieve("ETF", top_k=top_k)


def test_lexical_ranking_handles_empty_or_unmatched_passages():
    assert passage_scores("ETF", []) == []
    assert passage_scores("ETF", ["", "。！？"]) == [0, 0]
    assert passage_scores("NAV", ["bonds", "shares"]) == [0, 0]
