"""Lexical scoring for approved education passages, independent of storage provider."""

import re
from collections import Counter
from math import log

from app.core.guardrails import normalize_for_security_inspection
from app.core.telemetry import log_event

STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "is",
        "are",
        "be",
        "as",
        "with",
        "from",
        "about",
        "investment",
        "investments",
        "general",
        "education",
    ]
)


def terms(text: str) -> list[str]:
    log_event("VV entering ", "app.rag.ranking", "terms")
    text = normalize_for_security_inspection(text).casefold()
    text = text.replace("%", " percent ")
    for phrase, abbreviation in (
        (r"saving vs investing", "saving investing risk return liquidity horizon"),
        (r"exchange[ -]traded funds?", "etf"),
        (r"cpf investment scheme", "cpfis"),
        (r"ordinary account", "oa"),
        (r"special account", "sa"),
    ):
        text = re.sub(phrase, abbreviation, text)
    result = []
    for word in re.findall(r"[a-z0-9]+", text):
        if word in STOP_WORDS:
            continue
        if word.endswith("ies"):
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        word = {
            "lose": "loss",
            "losing": "loss",
            "drawdown": "loss",
            "tolerance": "appetite",
            "reserve": "aside",
            "stock": "share",
            "pooling": "pool",
            "pooled": "pool",
        }.get(word, word)
        result.append(word)
    return result



def passage_scores(query: str, passages: list[str]) -> list[float]:
    log_event("VV entering ", "app.rag.ranking", "passage_scores")
    if not passages:
        return []
    query = re.sub(r"^General investment education about\s+", "", query, flags=re.IGNORECASE)
    query_terms = set(terms(query))
    if "limit" in query_terms:
        query_terms.add("percent")
    counts = [Counter(terms(passage)) for passage in passages]
    frequency = Counter(term for count in counts for term in count)
    average_length = sum(sum(count.values()) for count in counts) / len(counts)
    if not average_length:
        return [0.0] * len(passages)
    return [
        sum(
            log(1 + (len(counts) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            * (count[term] * 2.5)
            / (count[term] + 1.5 * (0.25 + 0.75 * sum(count.values()) / average_length))
            for term in query_terms
            if count[term]
        )
        for count in counts
    ]
