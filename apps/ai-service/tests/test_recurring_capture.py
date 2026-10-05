import pytest

from app.agents.spending_capture import SpendingDraft
from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.recurring_fixture import apply_recurring_terms
from app.models.spending_fixture import fixture_spending_draft
from app.orchestrator import AgentOrchestrator


@pytest.mark.parametrize("text,frequency,interval", [
    ("monthly", "monthly", 1), ("weekly", "weekly", 1),
    ("annually", "yearly", 1), ("every 2 months", "monthly", 2),
])
def test_fixture_extracts_only_explicit_frequency(text, frequency, interval):
    payload = {"message": f"I paid SGD100 for {text} rent on 2026-01-31"}
    draft = SpendingDraft.model_validate(apply_recurring_terms(payload, fixture_spending_draft(payload)))
    item = draft.transactions[0]
    assert item.recurrence.frequency == frequency and item.recurrence.interval == interval
    assert item.recurrence.first_on is None and item.recurrence.next_due_on is None
    assert item.recurring and item.amount == 100


def test_merchant_does_not_establish_monthly_frequency():
    payload = {"message": "I paid SGD18 for Netflix on 2026-01-31"}
    draft = SpendingDraft.model_validate(apply_recurring_terms(payload, fixture_spending_draft(payload)))
    assert draft.transactions[0].recurrence is None and not draft.transactions[0].recurring


@pytest.mark.parametrize("terms,month_end", [
    ("month-end", True), ("on the last day of each month", True), ("monthly", False),
])
def test_explicit_month_end_is_preserved_without_inference(terms, month_end):
    payload = {"message": f"I paid SGD100 for rent {terms} on 2026-04-30"}
    draft = SpendingDraft.model_validate(apply_recurring_terms(payload, fixture_spending_draft(payload)))
    recurrence = draft.transactions[0].recurrence
    assert recurrence.frequency == "monthly" and recurrence.month_end is month_end
    assert recurrence.first_on is None and recurrence.next_due_on is None


def test_fixture_forecast_is_read_only_and_preserves_explicit_range():
    payload = {"message": "Forecast my recurring expenses from 2026-02-01 through 2026-03-31"}
    draft = SpendingDraft.model_validate(apply_recurring_terms(payload, fixture_spending_draft(payload)))
    assert draft.action == "forecast" and not draft.transactions
    assert draft.query_start.isoformat() == "2026-02-01" and draft.query_end.isoformat() == "2026-03-31"


@pytest.mark.parametrize("message,action", [
    ("I paid SGD100 for monthly rent on 2026-01-31", "record"),
    ("Forecast my recurring expenses from 2026-02-01 through 2026-02-28", "forecast"),
])
def test_semantic_fixture_route_reaches_explicit_cadence_or_forecast_extractor(message, action):
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(user_id="recurrence-u", session_id="recurrence-chat", message=message))
    result = next(item for item in response.agent_results if item.agent == "spending")
    assert not response.blocked and result.data["spending_draft"]["action"] == action
    if action == "record":
        assert result.data["spending_draft"]["transactions"][0]["recurrence"]["frequency"] == "monthly"
