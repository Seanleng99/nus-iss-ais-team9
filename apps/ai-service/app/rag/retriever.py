import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.config import Settings
from app.core.guardrails import sanitize_rag_document
from app.rag.ingestion import ApprovedDocumentMetadata

LOCAL_EDUCATION_CORPUS_VERSION = "investment-education-sg@local-fixture-v1"


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


def build_education_context(
    retriever: EducationRetriever,
    query: str,
    *,
    scope: str,
) -> dict[str, Any]:
    contexts = []
    for item in retriever.retrieve(query):
        context = asdict(item)
        decision = sanitize_rag_document(context["text"])
        context["text"] = decision.sanitized_text
        context["findings"] = list(
            dict.fromkeys([*context["findings"], *decision.findings])
        )
        contexts.append(context)
    sources = [
        {key: context[key] for key in SOURCE_METADATA_FIELDS}
        for context in contexts
    ]
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
            "investments can lose value."
        ),
        "keywords": {"beginner", "diversification", "etf", "investment", "risk"},
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
]


class LocalEducationRetriever:
    corpus_version = LOCAL_EDUCATION_CORPUS_VERSION
    expected_corpus_version = LOCAL_EDUCATION_CORPUS_VERSION

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        query_terms = set(re.findall(r"[a-z0-9]+", query.lower()))
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

            self._client = boto3.client(
                "bedrock-agent-runtime",
                region_name=self.aws_region,
            )
        return self._client

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        try:
            return self._retrieve(query, top_k)
        except Exception as exc:
            raise RetrievalError(
                "The approved education knowledge base could not be queried."
            ) from exc

    def _retrieve(self, query: str, top_k: int) -> list[RetrievedChunk]:
        response = self.client.retrieve(
            knowledgeBaseId=self.knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": top_k}
            },
        )
        results = []
        for item in response.get("retrievalResults", []):
            score = float(item.get("score", 0.0))
            if score < self.minimum_score:
                continue
            metadata = item["metadata"]
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
                    text=str(item["content"]["text"]),
                    score=score,
                )
            )
        return results


def create_education_retriever(settings: Settings) -> EducationRetriever:
    provider = settings.rag_provider.lower()
    if provider == "local_fixture" and settings.app_env.lower() in {"local", "test"}:
        return LocalEducationRetriever()
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
