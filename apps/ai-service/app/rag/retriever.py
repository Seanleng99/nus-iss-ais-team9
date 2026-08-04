from app.core.guardrails import sanitize_rag_document

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
