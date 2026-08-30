import re

EDUCATION_TOPIC_PHRASES: tuple[tuple[str, str], ...] = (
    ("diversification", "diversification"),
    ("risk tolerance", "risk tolerance"),
    ("investment risk", "investment risk"),
    ("time horizon", "investment time horizon"),
    ("investment horizon", "investment time horizon"),
    ("investment fees", "investment fees"),
    ("investment charges", "investment fees"),
    ("investing", "investment basics"),
    ("investment", "investment basics"),
    ("invest", "investment basics"),
    ("etf", "exchange-traded funds"),
    ("etfs", "exchange-traded funds"),
    ("cpf investment", "CPF Investment Scheme"),
    ("cpfis", "CPF Investment Scheme"),
)


def education_topics(message: str) -> list[str]:
    normalized = message.casefold()
    topics: list[str] = []
    for phrase, topic in EDUCATION_TOPIC_PHRASES:
        if (
            re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized)
            and topic not in topics
        ):
            topics.append(topic)
    return topics


def should_request_education_context(message: str) -> bool:
    return bool(education_topics(message))


def build_minimal_education_query(message: str) -> tuple[str, list[str]]:
    topics = education_topics(message)
    if not topics:
        raise ValueError("No allowlisted education topic was identified.")
    return f"General investment education about {', '.join(topics)}", topics
