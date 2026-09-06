import re

EDUCATION_TOPIC_PHRASES: tuple[tuple[str, str], ...] = (
    ("market risk", "market risk"),
    ("市场风险", "market risk"),
    ("credit risk", "credit risk"),
    ("信用风险", "credit risk"),
    ("liquidity risk", "liquidity risk"),
    ("流动性风险", "liquidity risk"),
    ("currency risk", "currency risk"),
    ("汇率风险", "currency risk"),
    ("货币风险", "currency risk"),
    ("counterparty risk", "counterparty risk"),
    ("交易对手风险", "counterparty risk"),
    ("tracking error", "tracking error"),
    ("跟踪误差", "tracking error"),
    ("追踪误差", "tracking error"),
    ("diversification", "diversification"),
    ("分散投资", "diversification"),
    ("多元化", "diversification"),
    ("risk tolerance", "risk tolerance"),
    ("风险承受能力", "risk tolerance"),
    ("investment risk", "investment risk"),
    ("投资风险", "investment risk"),
    ("time horizon", "investment time horizon"),
    ("investment horizon", "investment time horizon"),
    ("投资期限", "investment time horizon"),
    ("investment readiness", "investment readiness"),
    ("投资准备", "investment readiness"),
    ("risk and return", "risk and return"),
    ("risk-return", "risk and return"),
    ("risk return", "risk and return"),
    ("风险与回报", "risk and return"),
    ("investment limits", "investment limits"),
    ("投资限制", "investment limits"),
    ("investment fees", "investment fees"),
    ("investment charges", "investment fees"),
    ("fees", "investment fees"),
    ("charges", "investment fees"),
    ("费用", "investment fees"),
    ("shares", "shares"),
    ("share", "shares"),
    ("stocks", "shares"),
    ("stock", "shares"),
    ("股票", "shares"),
    ("bonds", "bonds"),
    ("bond", "bonds"),
    ("债券", "bonds"),
    ("unit trusts", "funds"),
    ("unit trust", "funds"),
    ("mutual funds", "funds"),
    ("mutual fund", "funds"),
    ("investment funds", "funds"),
    ("investment fund", "funds"),
    ("managed funds", "funds"),
    ("managed fund", "funds"),
    ("共同基金", "funds"),
    ("单位信托", "funds"),
    ("reits", "real estate investment trusts"),
    ("reit", "real estate investment trusts"),
    ("real estate investment trusts", "real estate investment trusts"),
    ("房地产投资信托", "real estate investment trusts"),
    ("exchange-traded funds", "exchange-traded funds"),
    ("exchange traded funds", "exchange-traded funds"),
    ("交易所交易基金", "exchange-traded funds"),
    ("交易所买卖基金", "exchange-traded funds"),
    ("etf", "exchange-traded funds"),
    ("etfs", "exchange-traded funds"),
    ("cpf investment", "CPF Investment Scheme"),
    ("cpfis", "CPF Investment Scheme"),
    ("公积金投资计划", "CPF Investment Scheme"),
)

GENERIC_EDUCATION_TOPIC_PHRASES = (
    "investing",
    "investment",
    "invest",
    "投资",
)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def _contains_phrase(normalized: str, phrase: str) -> bool:
    if _contains_cjk(phrase):
        return phrase in normalized
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized))


def education_topics(message: str) -> list[str]:
    normalized = message.casefold()
    topics: list[str] = []
    for phrase, topic in EDUCATION_TOPIC_PHRASES:
        if _contains_phrase(normalized, phrase) and topic not in topics:
            topics.append(topic)
    if not topics and any(
        _contains_phrase(normalized, phrase)
        for phrase in GENERIC_EDUCATION_TOPIC_PHRASES
    ):
        topics.append("investment basics")
    return topics


def education_response_language(message: str) -> str:
    return "Chinese" if _contains_cjk(message) else "English"


def should_request_education_context(message: str) -> bool:
    return bool(education_topics(message))


def build_minimal_education_query(message: str) -> tuple[str, list[str]]:
    topics = education_topics(message)
    if not topics:
        raise ValueError("No allowlisted education topic was identified.")
    return f"General investment education about {', '.join(topics)}", topics
