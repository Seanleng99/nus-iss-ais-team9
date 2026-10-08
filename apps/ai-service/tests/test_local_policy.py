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
        POLICY_CORPUS_VERSION="financial-coach-policy-sg@2026-10-09.1",
    )
    assert create_policy_retriever(config).expected_corpus_version == retriever.expected_corpus_version


def test_fixture_and_packaged_review_share_all_policy_meaning():
    from coach_trace.review import POLICY_CLAUSES

    from app.rag.policy import LocalPolicyRetriever

    packaged = LocalDocumentPolicyRetriever().retrieve("Explain a monthly budget.")
    fixture = LocalPolicyRetriever().retrieve("Explain a monthly budget.")
    assert {item.source_id: item.text for item in fixture} == {item.source_id: item.text for item in packaged}
    assert all(len(item.text) <= 6000 for item in packaged)
    assert all(any("## " + clause + " " in item.text for item in packaged) for clause in POLICY_CLAUSES)
    assert all(item.corpus_version.endswith("@local-fixture-v1") for item in fixture)
