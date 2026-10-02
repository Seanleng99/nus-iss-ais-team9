import pytest
from language_fixtures import language_case

from app.agents.education_access import (
    CANONICAL_EDUCATION_TOPICS,
    build_minimal_education_query,
    education_question_intent,
    education_topics,
)


def test_acronyms_match_when_adjacent_to_chinese_text() -> None:
    assert education_topics(
        language_case("education_access.test_acronyms_match_when_adjacent_to_chinese_text")
    ) == ["exchange-traded funds"]
    assert education_topics(
        language_case("education_access.test_acronyms_match_when_adjacent_to_chinese_text_2")
    ) == ["real estate investment trusts"]


def test_acronyms_match_with_punctuation_and_case() -> None:
    assert education_topics("ETF, etfs; REITs!") == [
        "real estate investment trusts",
        "exchange-traded funds",
    ]


def test_acronyms_do_not_match_inside_longer_ascii_words() -> None:
    assert education_topics("Explain ETFish products and preREITs analysis.") == []


def test_new_allowlisted_phrases_use_canonical_topics() -> None:
    assert education_topics(
        language_case("education_access.test_new_allowlisted_phrases_use_canonical_topics")
    ) == [
        "zero-coupon bonds",
        "bond duration",
        "treasury bills",
        "Singapore Savings Bonds",
        "dollar-cost averaging",
    ]


def test_unsupported_tax_concepts_remain_unallowlisted() -> None:
    assert education_topics("Explain capital gains tax.") == []
    assert education_topics("Explain tokenized-asset tax.") == []


def test_minimal_query_contains_topics_without_personal_data() -> None:
    query, topics = build_minimal_education_query(
        language_case("education_access.query_topics")
    )

    assert topics == ["exchange-traded funds"]
    assert query == "General investment education about exchange-traded funds"
    assert "9,876" not in query
    assert "learner@example.com" not in query


@pytest.mark.parametrize(
    "message",
    [
        "im new to investment, how do i start",
        "I am new to investing. How do I start?",
        "I'm new to investing. How do I start?",
        "I’m new to investing. How do I start?",
        "Where do I begin with investing?",
        "How can I get started with investing?",
    ],
)
def test_beginner_questions_use_canonical_investment_basics_query(message: str) -> None:
    assert build_minimal_education_query(message) == (
        "General investment education about investment basics",
        ["investment basics"],
    )


@pytest.mark.parametrize(
    "message",
    [
        "Explain the investment implications of extraterrestrial mineral rights.",
        "I am new to investment tax, how do I start?",
        "I am new to investing in alien artifacts, where should I start?",
        "What should I check before serving this recipe?",
        "This travel package says there is no risk. Is it legitimate?",
    ],
)
def test_unsupported_or_unrecognized_question_does_not_use_generic_fallback(
    message: str,
) -> None:
    assert education_topics(message) == []


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("I’m completely new to investing. Where should I start?", "investment basics"),
        ("Why invest instead of leaving all my money in savings?", "saving vs investing"),
        ("Could you show how interest earned on interest works?", "compound interest"),
        ("How might rising prices erode what my cash can buy?", "inflation"),
        ("What should I check before putting spare cash into investments?", "investment readiness"),
        ("How should my investment choices change with my goal date?", "investment time horizon"),
        ("How do I compare an index-tracking fund with a manager-picked fund?", "index funds"),
        ("My holdings fell sharply; what factors should I review?", "investment drawdowns"),
        (
            "Someone promises guaranteed monthly gains. How can I verify the offer?",
            "investment scams",
        ),
        (
            "Where can I independently confirm this financial explanation is current?",
            "source verification",
        ),
        ("What do exchange-rate movements mean for overseas holdings?", "currency risk"),
        ("How do fixed-term bank deposits compare with bonds?", "fixed deposits"),
        (
            language_case("education_access.test_beginner_paraphrases_map_to_canonical_topics"),
            "irregular income investment readiness",
        ),
        (
            language_case("education_access.test_beginner_paraphrases_map_to_canonical_topics_2"),
            "debt and investment readiness",
        ),
        (
            language_case("education_access.test_beginner_paraphrases_map_to_canonical_topics_3"),
            "fixed deposits",
        ),
        (
            language_case("education_access.test_beginner_paraphrases_map_to_canonical_topics_4"),
            "index funds",
        ),
        (
            language_case("education_access.test_beginner_paraphrases_map_to_canonical_topics_5"),
            "investment drawdowns",
        ),
        (
            language_case("education_access.test_beginner_paraphrases_map_to_canonical_topics_6"),
            "source verification",
        ),
        (
            "What reliable sources can I use to check your explanation, and how up to date are they?",
            "source verification",
        ),
    ],
)
def test_beginner_paraphrases_map_to_canonical_topics(message: str, topic: str) -> None:
    assert topic in education_topics(message)


def test_question_intent_keeps_comparison_and_detects_examples() -> None:
    assert education_question_intent("Compare saving and investing with an example") == "comparison"
    assert education_question_intent("Explain compound interest with a simple example") == "example"


def test_minimal_query_never_carries_personal_values() -> None:
    query, _ = build_minimal_education_query(
        "My income is SGD 8,432.50, email me@example.com, account 123456; can I afford to invest?"
    )
    assert query == "General investment education about investment readiness"
    assert all(value not in query for value in ("8,432.50", "me@example.com", "123456"))


def test_additional_canonical_topics_are_merged_in_order_and_validated() -> None:
    query, topics = build_minimal_education_query(
        "Explain compound interest.", additional_topics=("inflation", "compound interest")
    )
    assert topics == ["compound interest", "inflation"]
    assert query == "General investment education about compound interest, inflation"
    assert "investment basics" in CANONICAL_EDUCATION_TOPICS
    with pytest.raises(ValueError, match="canonical allowlisted"):
        build_minimal_education_query("Explain investing.", additional_topics=("model invented topic",))
