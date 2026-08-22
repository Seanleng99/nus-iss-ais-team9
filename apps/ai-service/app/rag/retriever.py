import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings
from app.core.guardrails import sanitize_rag_document


@dataclass(frozen=True)
class RetrievedChunk:
    source_id: str
    title: str
    issuing_organization: str
    canonical_url: str
    published_at: str
    text: str
    score: float
    findings: tuple[str, ...] = ()


class EducationRetriever(Protocol):
    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]: ...


class RetrievalError(RuntimeError):
    """Raised when approved education evidence cannot be retrieved safely."""


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
        "text": (
            "CPFIS offers investment choices with different risks and returns. Investors "
            "should consider their goals, time horizon, risk tolerance, diversification, and "
            "charges. CPF Board does not endorse a specific investment product."
        ),
        "keywords": {"cpf", "cpfis", "scheme", "savings", "charges"},
    },
]


class LocalEducationRetriever:
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
        minimum_score: float = 0.0,
        client: Any | None = None,
    ) -> None:
        self.knowledge_base_id = knowledge_base_id
        self.aws_region = aws_region
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
            results.append(
                RetrievedChunk(
                    source_id=str(metadata["source_id"]),
                    title=str(metadata["title"]),
                    issuing_organization=str(metadata["issuing_organization"]),
                    canonical_url=str(metadata["canonical_url"]),
                    published_at=str(metadata["published_at"]),
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
            minimum_score=settings.rag_minimum_score,
        )
    raise ValueError(
        f"Unsupported RAG_PROVIDER for APP_ENV={settings.app_env}: {provider}"
    )

TRUSTED_DOCUMENTS = [
    {
        "source_id": "mas-basic-financial-planning",
        "title": "MAS Basic Financial Planning Guide",
        "text": "Build an emergency fund, budget within your means, and understand investment risk.",
        "keywords": {"budget", "emergency", "risk", "planning"},
    },
    {
        "source_id": "cpf-savings-basics",
        "title": "CPF Savings Basics",
        "text": "CPF savings can support retirement, housing, and healthcare needs in Singapore.",
        "keywords": {"cpf", "retirement", "housing", "healthcare"},
    },
    {
        "source_id": "controlled-diversification-reference",
        "title": "Controlled Diversification Reference",
        "text": "Diversification spreads exposure across assets and can reduce concentration risk.",
        "keywords": {"investment", "diversification", "etf", "risk"},
    },
    {
        "source_id": "coach-advice-boundary-policy",
        "title": "Financial Coaching Advice Boundary",
        "text": (
            "The coach provides general education and must not issue personalized buy, sell, "
            "product, or guaranteed-return instructions."
        ),
        "keywords": {"advice", "buy", "sell", "stock", "recommendation", "guaranteed"},
    },
]


def retrieve_trusted_context(query: str, top_k: int = 3) -> list[dict[str, str]]:
    query_terms = set(query.lower().split())
    scored: list[tuple[int, dict[str, object]]] = []
    for document in TRUSTED_DOCUMENTS:
        score = len(query_terms.intersection(document["keywords"]))
        scored.append((score, document))
    ranked = sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
    contexts = []
    for score, document in ranked:
        sanitized = sanitize_rag_document(str(document["text"]))
        contexts.append(
            {
                "source_id": str(document["source_id"]),
                "title": str(document["title"]),
                "text": sanitized.sanitized_text,
                "score": str(score),
                "findings": ",".join(sanitized.findings),
            }
        )
    return contexts
