"""Local, governed full-document retrieval; a lexical baseline, not a Bedrock emulator."""

import re
from collections import Counter
from datetime import UTC, date, datetime
from hashlib import sha256
from math import log
from pathlib import Path

from app.core.guardrails import sanitize_rag_document
from app.core.telemetry import trace_method
from app.rag.ingestion import active_sources, governance_issues, load_source_manifest
from app.rag.ranking import terms
from app.rag.retriever import RetrievalError, RetrievedChunk, _is_trusted_education_url

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_KNOWLEDGE_ROOT = (_SERVICE_ROOT if (_SERVICE_ROOT / "knowledge").is_dir()
                   else Path(__file__).resolve().parents[4]) / "knowledge"
DEFAULT_CORPUS_ROOT = _KNOWLEDGE_ROOT / "investment_education"


def load_documents(
    manifest_path: Path,
    documents_dir: Path,
    *,
    as_of: date | None = None,
    allowed_url=_is_trusted_education_url,
):
    manifest = load_source_manifest(manifest_path)
    if governance_issues(manifest, as_of=as_of):
        raise RetrievalError("The local corpus is not currently approved.")
    documents = []
    root = documents_dir.resolve()
    for source in active_sources(manifest):
        path = (root / Path(source.s3_document_key).name).resolve()
        if (
            path.parent != root
            or not allowed_url(source.canonical_url)
            or sanitize_rag_document(f"{source.title} {source.issuing_organization}").findings
        ):
            raise RetrievalError("The local corpus contains an unapproved source location.")
        try:
            content = path.read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise RetrievalError("A local corpus document is unavailable.") from exc
        if "sha256:" + sha256(content).hexdigest() != source.checksum:
            raise RetrievalError("A local corpus document failed checksum verification.")
        if text.startswith("---\n"):
            text = text.split("\n---\n", 1)[-1]
        inspection = sanitize_rag_document(text)
        if not text.strip() or inspection.findings:
            raise RetrievalError("A local corpus document failed content inspection.")
        documents.append((source, text))
    if not documents:
        raise RetrievalError("The local corpus contains no approved documents.")
    return manifest, documents


def document_chunks(text: str) -> list[str]:
    # Preserve complete paragraphs and their following context. This also keeps
    # list headings with their values without reproducing whole documents per hit.
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    heading = ""
    for index in range(len(paragraphs)):
        current = paragraphs[index]
        if len(current.split()) <= 12 and not current.endswith(".") and not current.startswith("-"):
            heading = current
        parts = []
        for paragraph in paragraphs[index:]:
            if parts and len(" ".join(parts + [paragraph]).split()) > 360:
                break
            parts.append(paragraph)
        chunk = "\n\n".join(([heading] if heading and heading != parts[0] else []) + parts)
        if len(chunk) > 6_000:
            raise RetrievalError("A local corpus paragraph exceeds the context limit.")
        chunks.append(chunk)
    return chunks


class LocalDocumentEducationRetriever:
    def __init__(
        self,
        manifest_path: Path = DEFAULT_CORPUS_ROOT / "source_manifest.json",
        documents_dir: Path = DEFAULT_CORPUS_ROOT / "documents",
    ) -> None:
        self.manifest, documents = load_documents(manifest_path, documents_dir)
        self.expected_corpus_version = self.manifest.corpus_version
        self._chunks = [
            (source, chunk, Counter(terms(chunk)))
            for source, text in documents
            for chunk in document_chunks(text)
        ]
        self._frequency = Counter(term for _, _, counts in self._chunks for term in counts)
        self._average_length = sum(sum(c.values()) for _, _, c in self._chunks) / len(self._chunks)

    @trace_method
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if governance_issues(self.manifest, as_of=datetime.now(UTC).date()):
            raise RetrievalError("The local corpus requires a new review.")
        query = re.sub(r"^General investment education about\s+", "", query, flags=re.IGNORECASE)
        query_terms = set(terms(query))
        if "limit" in query_terms:
            query_terms.add("percent")
        ranked = []
        for source, chunk, counts in self._chunks:
            length = sum(counts.values())
            score = sum(
                log(
                    1
                    + (len(self._chunks) - self._frequency[term] + 0.5)
                    / (self._frequency[term] + 0.5)
                )
                * (counts[term] * 2.5)
                / (counts[term] + 1.5 * (0.25 + 0.75 * length / self._average_length))
                for term in query_terms
                if counts[term]
            )
            # Prefer definitions/headings for an exact requested concept.
            headings = [
                part.split(" – ")[0]
                for part in chunk.split("\n\n")
                if " – " in part or (len(part.split()) <= 12 and not part.endswith("."))
            ]
            score += max(
                (2 * len(query_terms & set(terms(heading))) for heading in headings), default=0
            )
            if score:
                ranked.append((score, source, chunk))
        ranked.sort(key=lambda row: row[0], reverse=True)
        selected = []
        for score, source, chunk in ranked:
            # Overlapping paragraph windows should not consume all three result slots.
            sentences = set(chunk.split("\n\n"))
            if any(
                source.source_id == old.source_id
                and len(sentences & set(old.text.split("\n\n"))) / max(1, len(sentences)) > 0.6
                for old in selected
            ):
                continue
            if sum(old.source_id == source.source_id for old in selected) >= 2:
                continue
            selected.append(
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
                    text=chunk,
                    score=score,
                )
            )
            if len(selected) == top_k:
                break
        return selected
