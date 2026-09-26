from datetime import UTC, datetime
from pathlib import Path

from app.rag.ingestion import load_source_manifest, metadata_for_source
from app.rag.policy import BedrockPolicyRetriever
from app.rag.retriever import BedrockEducationRetriever


def test_nonfinite_scores_and_duplicate_chunks_do_not_become_evidence():
    manifest = load_source_manifest(
        Path(__file__).resolve().parents[3] / "knowledge/investment_education/source_manifest.json"
    )
    metadata = metadata_for_source(
        manifest, manifest.sources[0], ingested_at=datetime(2026, 9, 6, tzinfo=UTC)
    ).model_dump(mode="json")
    metadata["review_due_at"] = "2099-12-31"

    class Client:
        def retrieve(self, **kwargs):
            return {"retrievalResults": [
                {"metadata": metadata, "content": {"text": "Diversification spreads exposure."}, "score": score}
                for score in [float("nan"), float("inf"), 0.95, 0.95]
            ]}

    retriever = BedrockEducationRetriever(
        knowledge_base_id="EDUCATION123", aws_region="ap-southeast-1",
        expected_corpus_version=manifest.corpus_version,
        minimum_score=0.6, client=Client(),
    )
    results = retriever.retrieve("General investment education about diversification")
    assert len(results) == 1
    assert results[0].score == 0.95


def test_both_retrieval_clients_have_bounded_network_attempts(monkeypatch):
    import boto3

    configurations = []

    def client(name, **kwargs):
        assert name == "bedrock-agent-runtime"
        configurations.append(kwargs["config"])
        return object()

    monkeypatch.setattr(boto3, "client", client)
    for retriever_type in (BedrockEducationRetriever, BedrockPolicyRetriever):
        retriever = retriever_type(
            knowledge_base_id="TESTKB123", aws_region="ap-southeast-1",
            expected_corpus_version="test-corpus@1",
        )
        assert retriever.client is not None
    for config in configurations:
        assert config.connect_timeout <= 3
        assert config.read_timeout <= 5
        assert config.retries["total_max_attempts"] <= 2
