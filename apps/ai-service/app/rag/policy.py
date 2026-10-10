import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.config import Settings
from app.core.guardrails import sanitize_rag_document
from app.core.telemetry import log_event, trace_method
from app.rag.ingestion import ApprovedDocumentMetadata, GovernedSource
from app.rag.local_documents import _KNOWLEDGE_ROOT
from app.rag.retriever import RetrievalError, RetrievedChunk

LOCAL_POLICY_CORPUS_VERSION = "financial-coach-policy-sg@local-fixture-v1"


class PolicyRetriever(Protocol):
    expected_corpus_version: str

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]: ...


_POLICY_KEYWORDS = {
    "coach-advice-boundary-policy": {
        "advice", "allocation", "budget", "buy", "education", "goal", "guaranteed",
        "investment", "product", "sell", "spending", "stock",
    },
    "coach-evidence-policy": {
        "citation", "context", "evidence", "explain", "grounded", "investment", "source", "uncertainty",
    },
    "coach-instruction-security-policy": {
        "credential", "guardrail", "instruction", "override", "prompt", "security", "tool",
    },
}


def _fixture_policy_documents():
    # Fixtures use the same policy meaning as the packaged corpus. Their synthetic
    # lifecycle remains separate so historical/offline tests do not expire.
    log_event("VV entering ", "app.rag.policy", "_fixture_policy_documents")
    root = _KNOWLEDGE_ROOT / "policy_controls"
    manifest = json.loads((root / "source_manifest.json").read_text(encoding="utf-8"))
    return [
        {**source, "corpus_version": LOCAL_POLICY_CORPUS_VERSION,
         "review_due_at": "2099-12-31",
         "text": (root / "documents" / Path(source["s3_document_key"]).name).read_text(encoding="utf-8"),
         "keywords": _POLICY_KEYWORDS[source["source_id"]]}
        for source in manifest["sources"]
    ]


POLICY_DOCUMENTS = _fixture_policy_documents()


class LocalPolicyRetriever:
    corpus_version = LOCAL_POLICY_CORPUS_VERSION
    expected_corpus_version = LOCAL_POLICY_CORPUS_VERSION

    @trace_method
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        log_event("VV entering ", "app.rag.policy.LocalPolicyRetriever", "retrieve")
        query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        scored = [
            (len(query_terms.intersection(document["keywords"])), document)
            for document in POLICY_DOCUMENTS
        ]
        relevant = sorted(scored, key=lambda item: item[0], reverse=True)
        # Review always needs all policy families, just like the packaged provider.
        # Lexical scores only order this offline fixture's documents.
        selected = relevant[:top_k]

        results = []
        for score, document in selected:
            sanitized = sanitize_rag_document(str(document["text"]))
            results.append(
                RetrievedChunk(
                    source_id=str(document["source_id"]),
                    title=str(document["title"]),
                    issuing_organization=str(document["issuing_organization"]),
                    canonical_url=str(document["canonical_url"]),
                    published_at=str(document["published_at"]),
                    document_version=str(document["document_version"]),
                    checksum=str(document["checksum"]),
                    corpus_version=str(document["corpus_version"]),
                    review_due_at=str(document["review_due_at"]),
                    text=sanitized.sanitized_text,
                    score=float(score),
                    findings=tuple(sanitized.findings),
                )
            )
        return results


class BedrockPolicyRetriever:
    def __init__(
        self,
        *,
        knowledge_base_id: str,
        aws_region: str,
        expected_corpus_version: str,
        minimum_score: float = 0.0,
        client: Any | None = None,
        required_sources: tuple[GovernedSource, ...] = (),
    ) -> None:
        log_event("VV entering ", "app.rag.policy.BedrockPolicyRetriever", "__init__")
        self.knowledge_base_id = knowledge_base_id
        self.aws_region = aws_region
        self.expected_corpus_version = expected_corpus_version
        self.minimum_score = minimum_score
        self._client = client
        self.required_sources = required_sources

    @property
    def client(self) -> Any:
        log_event("VV entering ", "app.rag.policy.BedrockPolicyRetriever", "client")
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-agent-runtime",
                region_name=self.aws_region,
                config=Config(
                    connect_timeout=3, read_timeout=5,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
            )
        return self._client

    @trace_method
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        log_event("VV entering ", "app.rag.policy.BedrockPolicyRetriever", "retrieve")
        try:
            return self._retrieve(query, top_k)
        except Exception as exc:
            raise RetrievalError(
                "The approved policy knowledge base could not be queried.",
                component="policy_retriever",
            ) from exc

    @trace_method
    def _retrieve(
        self, query: str, top_k: int, *, source_id: str | None = None,
    ) -> list[RetrievedChunk]:
        log_event("VV entering ", "app.rag.policy.BedrockPolicyRetriever", "_retrieve")
        if self.required_sources and source_id is None:
            # Every review needs every policy family. Public policy titles replace
            # personal draft text; per-source queries prevent one policy's chunks
            # from displacing the other controls in a relevance-ranked top three.
            results = []
            for source in self.required_sources:
                chunks = self._retrieve(source.title, 20, source_id=source.source_id)
                chunks = [chunk for chunk in chunks if (
                    chunk.source_id == source.source_id
                    and chunk.checksum == source.checksum
                    and chunk.document_version == source.document_version
                    and chunk.canonical_url == source.canonical_url
                )]
                if not chunks:
                    raise RetrievalError(
                        "Required approved policy evidence is unavailable.",
                        component="policy_retriever",
                    )
                results.append(replace(
                    chunks[0], text="\n\n".join(dict.fromkeys(chunk.text for chunk in chunks)),
                ))
            return results
        filters = [
            {"equals": {"key": "corpus_version", "value": self.expected_corpus_version}},
            {"equals": {"key": "review_status", "value": "approved"}},
        ]
        if source_id:
            filters.append({"equals": {"key": "source_id", "value": source_id}})
        log_event(
            "bedrock.retrieve.request", component="policy_retriever",
            knowledge_base_id=self.knowledge_base_id, corpus_version=self.expected_corpus_version,
            top_k=top_k,
        )
        response = self.client.retrieve(
            knowledgeBaseId=self.knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": top_k,
                    "filter": {"andAll": filters},
                }
            },
        )
        log_event(
            "bedrock.retrieve.response", component="policy_retriever",
            retrieved_chunk_count=len(response.get("retrievalResults", [])),
            status_code=response.get("ResponseMetadata", {}).get("HTTPStatusCode"),
        )
        results = []
        seen = set()
        for item in response.get("retrievalResults", []):
            if not isinstance(item, dict):
                continue
            try:
                score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                continue
            if not isfinite(score) or score < self.minimum_score:
                continue
            metadata = item.get("metadata")
            content = item.get("content")
            if not isinstance(metadata, dict) or not isinstance(content, dict):
                continue
            text = content.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            if metadata.get("review_status") != "approved":
                continue
            governance_metadata = {
                key: value
                for key, value in metadata.items()
                if not key.startswith("x-amz-bedrock-kb-")
            }
            try:
                governed = ApprovedDocumentMetadata.model_validate(governance_metadata)
            except ValidationError:
                continue
            if governed.corpus_version != self.expected_corpus_version:
                continue
            if governed.review_due_at < datetime.now(UTC).date():
                continue
            identity = (governed.source_id, governed.document_version, text.strip())
            if identity in seen:
                continue
            seen.add(identity)
            results.append(
                RetrievedChunk(
                    source_id=governed.source_id,
                    title=governed.title,
                    issuing_organization=governed.issuing_organization,
                    canonical_url=governed.canonical_url,
                    published_at=governed.published_at.isoformat(),
                    document_version=governed.document_version,
                    checksum=governed.checksum,
                    corpus_version=governed.corpus_version,
                    review_due_at=governed.review_due_at.isoformat(),
                    text=text,
                    score=score,
                )
            )
        return results


def create_policy_retriever(settings: Settings) -> PolicyRetriever:
    log_event("VV entering ", "app.rag.policy", "create_policy_retriever")
    provider = settings.policy_rag_provider.lower()
    if provider == "local_fixture" and settings.app_env.lower() in {"local", "test"}:
        return LocalPolicyRetriever()
    if provider == "local_documents":
        from app.rag.local_policy import DEFAULT_POLICY_ROOT, LocalDocumentPolicyRetriever

        retriever = LocalDocumentPolicyRetriever(
            Path(settings.policy_rag_manifest_path)
            if settings.policy_rag_manifest_path else DEFAULT_POLICY_ROOT / "source_manifest.json",
            Path(settings.policy_rag_documents_path)
            if settings.policy_rag_documents_path else DEFAULT_POLICY_ROOT / "documents",
        )
        if retriever.expected_corpus_version != settings.policy_corpus_version:
            raise ValueError("POLICY_CORPUS_VERSION must match the approved local manifest")
        return retriever
    if provider == "bedrock" and settings.policy_knowledge_base_id:
        from app.rag.local_policy import DEFAULT_POLICY_ROOT, LocalDocumentPolicyRetriever

        approved = LocalDocumentPolicyRetriever(
            Path(settings.policy_rag_manifest_path) if settings.policy_rag_manifest_path
            else DEFAULT_POLICY_ROOT / "source_manifest.json",
            Path(settings.policy_rag_documents_path) if settings.policy_rag_documents_path
            else DEFAULT_POLICY_ROOT / "documents",
        )
        if approved.expected_corpus_version != settings.policy_corpus_version:
            raise ValueError("POLICY_CORPUS_VERSION must match the approved manifest")
        return BedrockPolicyRetriever(
            knowledge_base_id=settings.policy_knowledge_base_id,
            aws_region=settings.aws_region,
            expected_corpus_version=settings.policy_corpus_version,
            minimum_score=settings.policy_rag_minimum_score,
            required_sources=tuple(source for source, _ in approved.documents),
        )
    raise ValueError(
        f"Unsupported POLICY_RAG_PROVIDER for APP_ENV={settings.app_env}: {provider}"
    )
