import re
from functools import lru_cache

from coach_i18n import (
    input_pattern,
    language_name,
    load_data,
    resolve_locale,
    topic_label,
    translate,
)

from app.core.telemetry import log_event

EDUCATION_TOPIC_PHRASES = load_data("education_vocabulary")["EDUCATION_TOPIC_PHRASES"]

# Canonical concepts preserve educational detail without embedding the user's
# amounts, identifiers, or unrestricted text in retrieval queries.
EDUCATION_DETAIL_PHRASES = load_data("education_vocabulary")["EDUCATION_DETAIL_PHRASES"]
PUBLIC_EDUCATION_SEARCH_ALIASES = load_data("education_vocabulary").get(
    "PUBLIC_EDUCATION_SEARCH_ALIASES", {},
)

CANONICAL_EDUCATION_TOPICS: tuple[str, ...] = tuple(dict.fromkeys(
    [topic for _, topic in EDUCATION_TOPIC_PHRASES]
    + [topic for topic, _ in EDUCATION_DETAIL_PHRASES]
    + ["investment basics", "general investment concepts"]
))

GENERIC_EDUCATION_TOPIC_PHRASES = load_data("education_vocabulary")["GENERIC_EDUCATION_TOPIC_PHRASES"]

GENERIC_EDUCATION_QUESTION = re.compile(
    input_pattern("ai.agents.education_access.generic_education_question")
)

UNSUPPORTED_EDUCATION_TOPIC_PHRASES = load_data("education_vocabulary")["UNSUPPORTED_EDUCATION_TOPIC_PHRASES"]

DETAILED_EDUCATION_TOPICS = {
    "bond duration", "bond convexity", "zero-coupon bonds", "treasury bills",
    "Singapore Savings Bonds", "dollar-cost averaging",
    "compound interest", "inflation", "fixed deposits", "investment scams",
}

CHINESE_GAP_LABELS = load_data("education_vocabulary")["CHINESE_GAP_LABELS"]


def unsupported_education_topics(message: str) -> list[str]:
    log_event("VV entering ", "app.agents.education_access", "unsupported_education_topics")
    return list(dict.fromkeys(
        topic for phrase, topic in UNSUPPORTED_EDUCATION_TOPIC_PHRASES
        if _contains_phrase(message.casefold(), phrase)
    ))


def education_question_intent(message: str) -> str:
    log_event("VV entering ", "app.agents.education_access", "education_question_intent")
    vocabulary = load_data("input_vocabulary")
    for phrases, intent in vocabulary["education_intents"]:
        if any(_contains_phrase(message.casefold(), phrase) for phrase in phrases):
            return intent
    if any(
        _contains_phrase(message.casefold(), phrase)
        for phrase in vocabulary["education_example_terms"]
    ):
        return "example"
    return "explanation"


def _contains_cjk(text: str) -> bool:
    log_event("VV entering ", "app.agents.education_access", "_contains_cjk")
    return bool(re.search(load_data("scripts")["han_basic"], text))


def _contains_phrase(normalized: str, phrase: str) -> bool:
    log_event("VV entering ", "app.agents.education_access", "_contains_phrase")
    phrase = phrase.casefold()
    if _contains_cjk(phrase):
        return phrase in normalized
    return bool(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(phrase)}(?![A-Za-z0-9_])", normalized)
    )


def ordered_education_topics(message: str, topics: list[str]) -> list[str]:
    """Use explicit option labels or mention order, never registry order."""
    log_event("VV entering ", "app.agents.education_access", "ordered_education_topics")
    numbered = list(
        re.finditer(input_pattern("ai.agents.education_access.numbered_options"), message)
    )
    if numbered:
        if [int(match[1]) for match in numbered] != list(range(1, len(numbered) + 1)):
            return []
        ordered = []
        for index, match in enumerate(numbered):
            end = numbered[index + 1].start() if index + 1 < len(numbered) else len(message)
            candidates = education_topics(message[match.end():end])
            if len(candidates) != 1 or candidates[0] not in topics:
                return []
            ordered.append(candidates[0])
    elif re.search(
        input_pattern("ai.agents.education_access.numbered_request"), message, re.IGNORECASE
    ):
        normalized = message.casefold()
        positions = {
            topic: min((match.start() for phrase, canonical in EDUCATION_TOPIC_PHRASES
                        if canonical == topic
                        for match in re.finditer(re.escape(phrase.casefold()), normalized)),
                       default=len(normalized))
            for topic in topics
        }
        if any(position == len(normalized) for position in positions.values()):
            return []
        ordered = sorted(topics, key=positions.get)
    else:
        return []
    return ordered if len(ordered) >= 2 and len(set(ordered)) == len(ordered) else []


def education_topics(message: str) -> list[str]:
    log_event("VV entering ", "app.agents.education_access", "education_topics")
    normalized = message.casefold()
    normalized = re.sub(
        input_pattern("ai.agents.education_access.capital_gains_tax"), "", normalized
    )
    broad_text = normalized
    for phrase, topic in EDUCATION_TOPIC_PHRASES:
        if topic in {"bond duration", "bond convexity", "zero-coupon bonds", "Singapore Savings Bonds"}:
            broad_text = broad_text.replace(phrase, " ")
    topics: list[str] = []
    for phrase, topic in EDUCATION_TOPIC_PHRASES:
        text = broad_text if topic == "bonds" else normalized
        if _contains_phrase(text, phrase) and topic not in topics:
            topics.append(topic)
    for topic, phrases in EDUCATION_DETAIL_PHRASES:
        if topic == "investment scams":
            has_scam_claim = any(_contains_phrase(normalized, phrase) for phrase in (
                "no risk", "without risk", "is it legitimate", "verify the offer",
                "whether it is legitimate", "guaranteed monthly gains",
            ))
            has_financial_context = any(
                _contains_phrase(normalized, phrase)
                for phrase in (
                    "investment",
                    "invest",
                    "return",
                    "pays",
                    "money",
                    "financial",
                    "gains",
                    input_pattern("ai.agents.education_access.investment_term"),
                    input_pattern("ai.agents.education_access.return_term"),
                )
            )
            matched = has_scam_claim and has_financial_context or any(
                _contains_phrase(normalized, phrase) for phrase in phrases
            )
        else:
            matched = any(_contains_phrase(normalized, phrase) for phrase in phrases)
        if topic == "investment time horizon" and not matched:
            matched = _contains_phrase(normalized, "goal date") and _contains_phrase(normalized, "investment choices")
        if matched and topic not in topics:
            if topic in {
                "debt and investment readiness",
                "irregular income investment readiness",
            } and not any(
                _contains_phrase(normalized, phrase)
                for phrase in GENERIC_EDUCATION_TOPIC_PHRASES
            ):
                continue
            if topic == "investment readiness emergency cash" and not any(
                _contains_phrase(normalized, phrase) for phrase in GENERIC_EDUCATION_TOPIC_PHRASES
            ):
                continue
            # Avoid adding a broader liquidity topic when liquidity risk was explicit.
            if topic == "liquidity" and "liquidity risk" in topics:
                continue
            topics.append(topic)
    if unsupported_education_topics(message) and "investment basics" in topics:
        topics.remove("investment basics")
    if topics and _contains_phrase(normalized, "risk") and not any("risk" in topic for topic in topics):
        topics.append("investment risk")
    if not topics and any(
        _contains_phrase(normalized, phrase)
        for phrase in GENERIC_EDUCATION_TOPIC_PHRASES
    ) and GENERIC_EDUCATION_QUESTION.fullmatch(normalized) and not unsupported_education_topics(message):
        topics.append("investment basics")
    return topics


def missing_education_topics(topics: list[str], contexts: list[dict]) -> list[str]:
    # Fine-grained concepts must appear in accepted evidence, not just a broad bond primer.
    log_event("VV entering ", "app.agents.education_access", "missing_education_topics")
    evidenced = {topic for context in contexts for topic in education_topics(context["text"])}
    return [topic for topic in topics if topic in DETAILED_EDUCATION_TOPICS - evidenced]


def apply_education_scope(
    grounding: dict, message: str, topics: list[str], *, semantic_assessment: bool = False,
) -> None:
    # Runtime semantic assessment checks the carried passages directly. Do not
    # discard them first because a concept's exact phrase was absent.
    log_event("VV entering ", "app.agents.education_access", "apply_education_scope")
    missing_topics = [] if semantic_assessment else missing_education_topics(topics, grounding["contexts"])
    if not semantic_assessment:
        missing_topics = list(dict.fromkeys(missing_topics + grounding.get("topics_without_context", [])))
    grounding["query_topics"] = list(topics)
    grounding["unanswered_topics"] = list(dict.fromkeys(
        unsupported_education_topics(message) + missing_topics
    ))
    grounding["question_intent"] = education_question_intent(message)
    grounding["response_language"] = education_response_language(message)
    if missing_topics and set(topics).issubset(missing_topics):
        grounding["contexts"] = []
        grounding["sources"] = []
        grounding["evidence_status"] = "insufficient"
    elif grounding["contexts"] and grounding["unanswered_topics"]:
        grounding["evidence_status"] = "partial"


def education_gap_message(grounding: dict) -> str:
    log_event("VV entering ", "app.agents.education_access", "education_gap_message")
    locale = grounding.get("response_language")
    topics = grounding.get("unanswered_topics", [])
    excluded = grounding.get("excluded_topics", [])
    separator = translate("education.topic_separator", locale)
    if excluded and not grounding.get("contexts") and not grounding.get("fallback_topics"):
        return translate(
            "education.outside_scope", locale,
            topics=separator.join(topic_label(topic, locale) for topic in excluded),
        )
    if grounding.get("coverage_assessment") == "semantic_contract_unverified":
        return translate("education.verification_unavailable", locale)
    message = translate("education.insufficient_evidence", locale)
    if topics:
        message += translate(
            "education.uncovered_topics", locale,
            topics=separator.join(topic_label(topic, locale) for topic in topics),
        )
    return message


def education_response_language(message: str) -> str:
    log_event("VV entering ", "app.agents.education_access", "education_response_language")
    return language_name(resolve_locale(message))


def education_model_question(message: str) -> str:
    """Retain the question's meaning without passing identifiers or personal sums."""
    log_event("VV entering ", "app.agents.education_access", "education_model_question")
    from app.core.guardrails import redact_sensitive_text

    message, _ = redact_sensitive_text(message)
    message = re.sub(r"\[REDACTED_[A-Z_]+\]", "", message)
    message = re.sub(
        r"(?:SGD|USD|S\$|US\$|\$)\s*\d[\d,]*(?:\.\d+)?",
        "(amount omitted)", message, flags=re.IGNORECASE,
    )
    message = re.sub(
        r"(?i)\b(?:account|salary|income|balance)\s*(?:is|of|:)?\s*\d[\d,.]*",
        "(personal value omitted)", message,
    )
    return message.strip()


def should_request_education_context(message: str) -> bool:
    log_event("VV entering ", "app.agents.education_access", "should_request_education_context")
    return bool(education_topics(message))


def build_minimal_education_query(
    message: str, *, additional_topics: tuple[str, ...] | list[str] = (),
    additional_search_terms: tuple[str, ...] | list[str] = (),
) -> tuple[str, list[str]]:
    log_event("VV entering ", "app.agents.education_access", "build_minimal_education_query")
    invalid_topics = [topic for topic in additional_topics if topic not in CANONICAL_EDUCATION_TOPICS]
    if invalid_topics:
        raise ValueError("Additional education topics must be canonical allowlisted topics.")
    topics = list(dict.fromkeys(education_topics(message) + list(additional_topics)))
    if len(topics) > 1 and "investment basics" in topics:
        topics.remove("investment basics")
    if not topics:
        raise ValueError("No allowlisted education topic was identified.")
    query = f"General investment education about {', '.join(topics)}"
    concepts = public_education_search_terms(additional_search_terms)
    if concepts:
        query += "; concepts: " + ", ".join(concepts)
    return query, topics


@lru_cache(maxsize=1)
def _public_education_words() -> frozenset[str]:
    # Retrieval terms can only contain words already present in the governed
    # public corpus. Never concatenate the user's free text into a query.
    log_event("VV entering ", "app.agents.education_access", "_public_education_words")
    from app.rag.local_documents import DEFAULT_CORPUS_ROOT, load_documents

    _, documents = load_documents(
        DEFAULT_CORPUS_ROOT / "source_manifest.json", DEFAULT_CORPUS_ROOT / "documents",
    )
    return frozenset(re.findall(
        r"[a-z]+", " ".join(text for _, text in documents).casefold(),
    ))


def public_education_search_terms(candidates: tuple[str, ...] | list[str]) -> list[str]:
    log_event("VV entering ", "app.agents.education_access", "public_education_search_terms")
    if not candidates:
        return []
    vocabulary = _public_education_words()
    forbidden = {"my", "your", "account", "password", "secret", "ignore", "instruction",
                 "system", "email", "phone", "name", "user", "salary"}
    result = []
    for candidate in candidates[:12]:
        if not isinstance(candidate, str):
            continue
        # Exact governed aliases admit public account/scam concepts without
        # accepting arbitrary credential values or the user's account details.
        candidate = " ".join(candidate.casefold().split())
        candidate = PUBLIC_EDUCATION_SEARCH_ALIASES.get(candidate, candidate)
        if not re.fullmatch(r"[A-Za-z][A-Za-z -]{1,79}", candidate):
            continue
        words = set(re.findall(r"[a-z]+", candidate.casefold()))
        if words and words.issubset(vocabulary) and not words.intersection(forbidden):
            result.append(candidate.casefold().strip())
    return list(dict.fromkeys(result))
