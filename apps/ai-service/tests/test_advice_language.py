import pytest

from app.agents.risk_compliance import financial_advice_findings


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
