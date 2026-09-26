import pytest

from app.agents.education_access import build_minimal_education_query, education_topics


def test_acronyms_match_when_adjacent_to_chinese_text() -> None:
    assert education_topics("请解释ETF的风险") == ["exchange-traded funds"]
    assert education_topics("请解释REITs") == ["real estate investment trusts"]


def test_acronyms_match_with_punctuation_and_case() -> None:
    assert education_topics("ETF, etfs; REITs!") == [
        "real estate investment trusts",
        "exchange-traded funds",
    ]


def test_acronyms_do_not_match_inside_longer_ascii_words() -> None:
    assert education_topics("Explain ETFish products and preREITs analysis.") == []


def test_new_allowlisted_phrases_use_canonical_topics() -> None:
    assert education_topics(
        "Explain DCA, 定投, T-bills, 国库券, SSBs, 新加坡储蓄债券, "
        "zero-coupon bonds, 零息债券, bond duration, and 债券久期."
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
        "I earn SGD 9,876 and my email is learner@example.com. Explain ETF的风险。"
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
    ],
)
def test_unsupported_or_unrecognized_question_does_not_use_generic_fallback(
    message: str,
) -> None:
    assert education_topics(message) == []
