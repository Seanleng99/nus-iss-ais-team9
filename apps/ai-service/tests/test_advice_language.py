import pytest

from app.agents.risk_compliance import contains_return_guarantee, financial_advice_findings

SAFE_GUARANTEE_ASSESSMENTS = [
    "The response avoids making any claims about guaranteed returns or specific investment outcomes.",
    (
        "The answer avoids personalized buy, sell, hold, allocation, product, or "
        "guaranteed-return instructions, and it clearly distinguishes educational warnings "
        "or negations about guaranteed returns from promises or requests for such returns."
    ),
    "The response makes no claims about guaranteed returns.",
    "The answer does not promise guaranteed returns.",
    "No guaranteed returns are promised.",
]

SAFE_EXECUTION_DESCRIPTIONS = [
    "Brokerage commissions may apply when you buy or sell ETFs on SGX.",
    (
        "Tracking error may arise because the fund manager cannot buy or sell component "
        "stocks in the index proportions."
    ),
    (
        "Tracking error can arise from execution costs, timing differences, or the "
        "inability to buy or sell component stocks in their exact proportion."
    ),
    (
        "Factors contributing to tracking error include the inability of the manager "
        "to buy or sell component stocks in their exact proportion."
    ),
    (
        "Tracking error can arise from the inability of the ETF manager to buy or sell "
        "the component stocks in their exact proportion."
    ),
    "The inability of the fund manager to buy or sell component stocks can cause tracking error.",
]

CLAUSE_SEPARATORS = [". ", "; ", "! ", "? ", "\n", ", ", ", but "]


@pytest.mark.parametrize("text", [
    "The manager's inability to buy or sell component stocks in their exact proportion may cause tracking error.",
    "In cash-based ETFs, the manager may be unable to buy or sell the component stocks in their exact proportion.",
    "The response does not provide personalized buy or sell instructions.",
])
def test_approved_execution_description_and_negated_policy_instruction_are_allowed(text):
    assert financial_advice_findings(text) == []


@pytest.mark.parametrize("text", [
    "Buy or sell shares now.",
    "Tell me whether to buy or sell this ETF.",
    "The manager's inability to buy or sell component stocks causes tracking error. You should buy this ETF.",
    "No personalized buy or sell instructions. Buy or sell this ETF now.",
    "The manager may be unable to buy or sell the component stocks. You should buy this ETF.",
])
def test_transaction_requests_and_mixed_unsafe_clauses_remain_blocked(text):
    assert financial_advice_findings(text)


@pytest.mark.parametrize("text", SAFE_GUARANTEE_ASSESSMENTS)
def test_negated_guarantee_policy_assessments_are_allowed(text):
    assert not contains_return_guarantee(text)
    assert financial_advice_findings(text) == []


@pytest.mark.parametrize("text", [
    "Give me an investment with a guaranteed return.",
    "This investment offers a guaranteed return.",
    "The response promises guaranteed returns.",
    "These ETF returns are guaranteed.",
    "Your return will be guaranteed.",
])
def test_positive_guarantee_requests_and_claims_remain_blocked(text):
    assert contains_return_guarantee(text)
    assert "regulated_advice:guaranteed return" in financial_advice_findings(text)


@pytest.mark.parametrize("safe_prefix", SAFE_GUARANTEE_ASSESSMENTS)
@pytest.mark.parametrize("separator", CLAUSE_SEPARATORS)
@pytest.mark.parametrize("unsafe_suffix", [
    "Give me an investment with a guaranteed return.",
    "This investment offers a guaranteed return.",
    "These ETF returns are guaranteed.",
])
def test_negated_policy_prefix_cannot_hide_guarantee_request_or_claim(
    safe_prefix, separator, unsafe_suffix,
):
    text = safe_prefix.removesuffix(".") + separator + unsafe_suffix
    assert contains_return_guarantee(text)
    assert "regulated_advice:guaranteed return" in financial_advice_findings(text)


@pytest.mark.parametrize("text", SAFE_EXECUTION_DESCRIPTIONS)
def test_bounded_brokerage_and_tracking_descriptions_are_allowed(text):
    assert financial_advice_findings(text) == []


@pytest.mark.parametrize("text", [
    "Brokerage commissions may apply, but tell me whether to buy or sell ETFs on SGX.",
    "Tracking error may arise, but tell me whether to buy or sell component stocks.",
    "The inability to time markets means you should buy or sell component stocks now.",
    "Tell me how to overcome the inability to buy or sell this ETF.",
    (
        "The fund manager recommends that you buy or sell component stocks "
        "in the index proportions."
    ),
])
def test_execution_vocabulary_does_not_allow_transaction_requests(text):
    assert "regulated_advice:buy or sell" in financial_advice_findings(text)


@pytest.mark.parametrize(
    "safe_prefix", SAFE_GUARANTEE_ASSESSMENTS + SAFE_EXECUTION_DESCRIPTIONS,
)
@pytest.mark.parametrize("separator", CLAUSE_SEPARATORS)
@pytest.mark.parametrize("recommendation", [
    "You should buy this ETF.",
    "You should sell this ETF.",
])
def test_safe_prefix_cannot_hide_transaction_recommendation(
    safe_prefix, separator, recommendation,
):
    text = safe_prefix.removesuffix(".") + separator + recommendation
    assert "regulated_advice:personalized_transaction" in financial_advice_findings(text)
