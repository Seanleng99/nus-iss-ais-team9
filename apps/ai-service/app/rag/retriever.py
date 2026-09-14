import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import ValidationError

from app.core.config import Settings
from app.core.guardrails import sanitize_rag_document
from app.core.telemetry import log_event, trace_method
from app.rag.ingestion import ApprovedDocumentMetadata

LOCAL_EDUCATION_CORPUS_VERSION = "investment-education-sg@local-fixture-v1"
MAX_EDUCATION_CHUNK_CHARACTERS = 6_000
TRUSTED_EDUCATION_SOURCE_DOMAINS = frozenset(
    {"cpf.gov.sg", "moneysense.gov.sg", "mas.gov.sg", "gov.sg"}
)


@dataclass(frozen=True)
class RetrievedChunk:
    source_id: str
    title: str
    issuing_organization: str
    canonical_url: str
    published_at: str
    document_version: str
    checksum: str
    corpus_version: str
    review_due_at: str
    text: str
    score: float
    findings: tuple[str, ...] = ()


class EducationRetriever(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]: ...


class RetrievalError(RuntimeError):
    """Raised when approved retrieval evidence cannot be queried safely."""

    code = "RETRIEVAL_ERROR"

    def __init__(self, message: str, *, component: str = "education_retriever") -> None:
        super().__init__(message)
        self.component = component


SOURCE_METADATA_FIELDS = (
    "source_id",
    "title",
    "issuing_organization",
    "canonical_url",
    "published_at",
    "document_version",
    "checksum",
    "corpus_version",
    "review_due_at",
)


def _is_trusted_education_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").casefold()
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in TRUSTED_EDUCATION_SOURCE_DOMAINS
    )


@trace_method
def build_education_context(
    retriever: EducationRetriever,
    query: str,
    *,
    scope: str,
) -> dict[str, Any]:
    contexts = []
    rejected_chunk_count = 0
    security_findings: list[str] = []
    retrieved = retriever.retrieve(query)
    for item in retrieved:
        context = asdict(item)
        metadata_decision = sanitize_rag_document(
            " ".join(
                str(context[key]) for key in ("title", "issuing_organization")
            )
        )
        if metadata_decision.findings:
            rejected_chunk_count += 1
            security_findings.extend(
                f"retrieval_metadata:{finding}"
                for finding in metadata_decision.findings
            )
            continue
        if len(context["text"]) > MAX_EDUCATION_CHUNK_CHARACTERS:
            rejected_chunk_count += 1
            security_findings.append("retrieval_content:chunk_too_large")
            continue
        decision = sanitize_rag_document(context["text"])
        context["text"] = decision.sanitized_text
        context["findings"] = list(
            dict.fromkeys([*context["findings"], *decision.findings])
        )
        security_findings.extend(context["findings"])
        if any(
            finding.startswith("indirect_prompt_injection:")
            for finding in context["findings"]
        ):
            rejected_chunk_count += 1
            continue
        contexts.append(context)
    sources = [
        {key: context[key] for key in SOURCE_METADATA_FIELDS}
        for context in contexts
    ]
    log_event(
        "rag.education.context.ready",
        retrieved_chunk_count=len(retrieved), accepted_chunk_count=len(contexts),
        rejected_chunk_count=rejected_chunk_count,
        evidence_status="grounded" if contexts else "insufficient",
        corpus_version=getattr(retriever, "expected_corpus_version", None),
    )
    return {
        "scope": scope,
        "evidence_status": "grounded" if contexts else "insufficient",
        "corpus_version": getattr(
            retriever,
            "expected_corpus_version",
            getattr(retriever, "corpus_version", None),
        ),
        "contexts": contexts,
        "sources": sources,
        "retrieved_chunk_count": len(retrieved),
        "accepted_chunk_count": len(contexts),
        "rejected_chunk_count": rejected_chunk_count,
        "security_findings": list(dict.fromkeys(security_findings)),
    }


EDUCATION_DOCUMENTS = [
    {
        "source_id": "cpf-beginners-guide-to-investing",
        "title": "A beginner's guide to investing in Singapore",
        "issuing_organization": "CPF Board",
        "canonical_url": (
            "https://www.cpf.gov.sg/member/infohub/educational-resources/"
            "a-beginners-guide-to-investing-in-singapore"
        ),
        "published_at": "2026-05-07",
        "document_version": "2026-05-07",
        "checksum": "sha256:6ccc58448539481c9b0e48eb1a54e7a09e9259e081a53866e25863c6a5031ab8",
        "corpus_version": LOCAL_EDUCATION_CORPUS_VERSION,
        "review_due_at": "2099-12-31",
        "text": (
            "Investment education should consider time horizon, risk tolerance, fees, and "
            "diversification. Exchange-traded funds are one investment type, and all "
            "investments can lose value. Treasury bills are issued at a discount and "
            "redeemed at face value at maturity. Singapore Savings Bonds are "
            "government-issued savings bonds."
        ),
        "keywords": {
            "beginner", "diversification", "etf", "investment", "risk",
            "treasury", "bills", "singapore", "savings",
        },
    },
    {
        "source_id": "cpf-investment-scheme-guide",
        "title": "CPF Investment Scheme: what you need to know about CPFIS",
        "issuing_organization": "CPF Board",
        "canonical_url": (
            "https://www.cpf.gov.sg/member/infohub/educational-resources/"
            "cpf-investment-scheme-what-you-need-to-know-about-cpfis"
        ),
        "published_at": "2026-02-09",
        "document_version": "2026-02-09",
        "checksum": "sha256:d4989883b6f95845051b98a9164ad21f107a7e90aa00d23ac7a7f4fa0cb5de91",
        "corpus_version": LOCAL_EDUCATION_CORPUS_VERSION,
        "review_due_at": "2099-12-31",
        "text": (
            "CPFIS offers investment choices with different risks and returns. Investors "
            "should consider their goals, time horizon, risk tolerance, diversification, and "
            "charges. CPF Board does not endorse a specific investment product."
        ),
        "keywords": {"cpf", "cpfis", "scheme", "savings", "charges"},
    },
    {
        "source_id": "moneysense-what-is-investing",
        "title": "What is investing?",
        "issuing_organization": "MoneySense / Monetary Authority of Singapore",
        "canonical_url": "https://www.moneysense.gov.sg/investments/what-is-investing/",
        "published_at": "2026-07-02",
        "document_version": "2026-07-02",
        "checksum": "sha256:0ceb1106fd69afa428cd9b242f9a372e4040f8aadc582ca7eb56634aa5480f61",
        "corpus_version": LOCAL_EDUCATION_CORPUS_VERSION,
        "review_due_at": "2099-12-31",
        "text": (
            "This approved guide introduces investment readiness, basic risk-and-return "
            "concepts, and the importance of an investment time horizon. Investments "
            "can lose value and returns are not guaranteed."
        ),
        "keywords": {"investment", "investing", "readiness", "risk", "return", "horizon"},
    },
    {
        "source_id": "moneysense-managing-investment-risk",
        "title": "Managing investment risk",
        "issuing_organization": "MoneySense / Monetary Authority of Singapore",
        "canonical_url": "https://www.moneysense.gov.sg/investments/investment-risk/",
        "published_at": "2026-07-02",
        "document_version": "2026-07-02",
        "checksum": "sha256:9c059618166ab8ed0051493b3ab680d6e85564fdf0db45c2dd0a1f5b05f387de",
        "corpus_version": LOCAL_EDUCATION_CORPUS_VERSION,
        "review_due_at": "2099-12-31",
        "text": (
            "This approved guide covers market, credit, liquidity, and currency risk, "
            "as well as diversification. Diversification can reduce concentration but "
            "does not remove the possibility of loss. Dollar-cost averaging means "
            "investing a fixed sum at regular intervals regardless of market movements."
        ),
        "keywords": {
            "investment",
            "risk",
            "market",
            "credit",
            "liquidity",
            "currency",
            "diversification",
            "dollar", "cost", "averaging",
        },
    },
    {
        "source_id": "moneysense-types-of-investments",
        "title": "An introduction to types of investments",
        "issuing_organization": "MoneySense / Monetary Authority of Singapore",
        "canonical_url": "https://www.moneysense.gov.sg/investments/types-of-investments/",
        "published_at": "2026-07-02",
        "document_version": "2026-07-02",
        "checksum": "sha256:87c2cc4c330d932f928654756bd26f526f1c0ab1f11529753983f28a453b6592",
        "corpus_version": LOCAL_EDUCATION_CORPUS_VERSION,
        "review_due_at": "2099-12-31",
        "text": (
            "This approved guide introduces shares, bonds, funds, exchange-traded "
            "funds, and real estate investment trusts as different investment types. "
            "Their structures, risks, liquidity, fees, and potential returns differ."
        ),
        "keywords": {
            "shares",
            "stocks",
            "bonds",
            "funds",
            "etf",
            "reits",
            "real", "estate", "trusts",
            "types",
        },
    },
    {
        "source_id": "moneysense-guide-to-etfs",
        "title": "Guide to ETFs: Understanding Exchange-Traded Funds",
        "issuing_organization": "MoneySense / Monetary Authority of Singapore",
        "canonical_url": (
            "https://www.moneysense.gov.sg/"
            "guide-to-etfs-understanding-exchange-traded-funds/"
        ),
        "published_at": "2026-07-02",
        "document_version": "2026-07-02",
        "checksum": "sha256:0d38a73ed5c009cb04d7c6c2cda5478f6e1bc4cc806cdf47200dfdb5c243db96",
        "corpus_version": LOCAL_EDUCATION_CORPUS_VERSION,
        "review_due_at": "2099-12-31",
        "text": (
            "This approved guide explains exchange-traded funds and educational "
            "considerations including fees, liquidity, tracking error, and counterparty "
            "risk. ETF values and returns are not guaranteed."
        ),
        "keywords": {
            "etf",
            "exchange",
            "traded",
            "funds",
            "fees",
            "liquidity",
            "tracking",
            "error",
            "counterparty",
            "risk",
        },
    },
]


class LocalEducationRetriever:
    corpus_version = LOCAL_EDUCATION_CORPUS_VERSION
    expected_corpus_version = LOCAL_EDUCATION_CORPUS_VERSION

    @trace_method
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        topic_query = re.sub(
            r"^general investment education about\s+",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query_terms = set(re.findall(r"[a-z0-9]+", topic_query.lower()))
        scored = [
            (len(query_terms.intersection(document["keywords"])), document)
            for document in EDUCATION_DOCUMENTS
        ]
        relevant = sorted(
            (item for item in scored if item[0] > 0),
            key=lambda item: item[0],
            reverse=True,
        )[:top_k]
        results = []
        for score, document in relevant:
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


class BedrockEducationRetriever:
    def __init__(
        self,
        *,
        knowledge_base_id: str,
        aws_region: str,
        expected_corpus_version: str,
        minimum_score: float = 0.0,
        client: Any | None = None,
    ) -> None:
        self.knowledge_base_id = knowledge_base_id
        self.aws_region = aws_region
        self.expected_corpus_version = expected_corpus_version
        self.minimum_score = minimum_score
        self._client = client

    @property
    def client(self) -> Any:
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
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        try:
            return self._retrieve(query, top_k)
        except Exception as exc:
            raise RetrievalError(
                "The approved education knowledge base could not be queried."
            ) from exc

    @trace_method
    def _retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        log_event(
            "bedrock.retrieve.request", component="education_retriever",
            knowledge_base_id=self.knowledge_base_id, corpus_version=self.expected_corpus_version,
            top_k=top_k,
        )
        response = self.client.retrieve(
            knowledgeBaseId=self.knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 20,
                    "filter": {
                        "andAll": [
                            {"equals": {"key": "corpus_version", "value": self.expected_corpus_version}},
                            {"equals": {"key": "review_status", "value": "approved"}},
                        ]
                    },
                }
            },
        )
        log_event(
            "bedrock.retrieve.response", component="education_retriever",
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
            if not _is_trusted_education_url(governed.canonical_url):
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
        # Semantic retrieval finds candidate documents; lexical scoring selects
        # the passages addressing the requested concepts within the same budget.
        from app.rag.ranking import passage_scores

        scores = passage_scores(query, [item.text for item in results])
        ranked = sorted(range(len(results)), key=lambda index: scores[index], reverse=True)
        return [results[index] for index in ranked[:top_k]]


def create_education_retriever(settings: Settings) -> EducationRetriever:
    provider = settings.rag_provider.lower()
    if provider == "local_fixture" and settings.app_env.lower() in {"local", "test"}:
        return LocalEducationRetriever()
    if provider == "local_documents" and settings.app_env.lower() in {"local", "test"}:
        from pathlib import Path

        from app.rag.local_documents import DEFAULT_CORPUS_ROOT, LocalDocumentEducationRetriever

        retriever = LocalDocumentEducationRetriever(
            Path(settings.rag_manifest_path) if settings.rag_manifest_path else DEFAULT_CORPUS_ROOT / "source_manifest.json",
            Path(settings.rag_documents_path) if settings.rag_documents_path else DEFAULT_CORPUS_ROOT / "documents",
        )
        if retriever.expected_corpus_version != settings.education_corpus_version:
            raise ValueError("EDUCATION_CORPUS_VERSION must match the approved local manifest")
        return retriever
    if provider == "bedrock" and settings.education_knowledge_base_id:
        return BedrockEducationRetriever(
            knowledge_base_id=settings.education_knowledge_base_id,
            aws_region=settings.aws_region,
            expected_corpus_version=settings.education_corpus_version,
            minimum_score=settings.rag_minimum_score,
        )
    raise ValueError(
        f"Unsupported RAG_PROVIDER for APP_ENV={settings.app_env}: {provider}"
    )
