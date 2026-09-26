"""Governed policy retrieval from the packaged, checksum-verified corpus."""

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.rag.ingestion import governance_issues
from app.rag.local_documents import _KNOWLEDGE_ROOT, load_documents
from app.rag.retriever import RetrievalError, RetrievedChunk

DEFAULT_POLICY_ROOT = _KNOWLEDGE_ROOT / "policy_controls"


def _is_trusted_policy_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.path.startswith(
            "/Seanleng99/nus-iss-ais-team9/blob/main/knowledge/policy_controls/documents/"
        )
    )


class LocalDocumentPolicyRetriever:
    def __init__(
        self,
        manifest_path: Path = DEFAULT_POLICY_ROOT / "source_manifest.json",
        documents_dir: Path = DEFAULT_POLICY_ROOT / "documents",
    ) -> None:
        self.manifest, self.documents = load_documents(
            manifest_path, documents_dir, allowed_url=_is_trusted_policy_url
        )
        self.expected_corpus_version = self.manifest.corpus_version

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        del query
        if not 1 <= top_k <= 3:
            raise ValueError("top_k must be between 1 and 3")
        if governance_issues(self.manifest, as_of=datetime.now(UTC).date()):
            raise RetrievalError("The policy corpus requires a new review.", component="policy_retriever")
        # All three short documents are required for independent compliance review.
        return [
            RetrievedChunk(
                source_id=source.source_id,
                title=source.title,
                issuing_organization=source.issuing_organization,
                canonical_url=source.canonical_url,
                published_at=source.published_at.isoformat(),
                document_version=source.document_version,
                checksum=source.checksum,
                corpus_version=self.expected_corpus_version,
                review_due_at=source.review_due_at.isoformat(),
                text=text,
                score=1.0,
            )
            for source, text in self.documents
        ][:top_k]
