from app.core.config import Settings
from app.rag.local_policy import LocalDocumentPolicyRetriever
from app.rag.policy import create_policy_retriever


def test_packaged_policy_corpus_is_complete_and_pinned():
    retriever = LocalDocumentPolicyRetriever()
    results = retriever.retrieve("personalized investment allocation")
    assert {item.source_id for item in results} == {
        "coach-advice-boundary-policy",
        "coach-evidence-policy",
        "coach-instruction-security-policy",
    }
    assert all(item.text and item.checksum.startswith("sha256:") for item in results)
    config = Settings(
        POLICY_RAG_PROVIDER="local_documents",
        POLICY_CORPUS_VERSION="financial-coach-policy-sg@2026-08-29.1",
    )
    assert create_policy_retriever(config).expected_corpus_version == retriever.expected_corpus_version
