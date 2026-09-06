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
