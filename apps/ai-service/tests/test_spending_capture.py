from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.orchestrator import AgentOrchestrator


def run(message, **kwargs):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(
        CoachRequest(user_id="u1", session_id="s1", message=message, **kwargs)
    )


def test_record_statement_extracts_unsaved_spending_draft():
    reply = run("i spent $5 on chicken rice")
    assert not reply.blocked
    result = next(r for r in reply.agent_results if r.agent == "spending")
    draft = result.data["spending_draft"]
    assert draft["action"] == "record"
    assert draft["persistence_intent"] == "save"
    assert draft["transactions"][0]["amount"] == 5.0
    assert draft["transactions"][0]["description"] == "chicken rice"
    assert "unsaved" in result.summary
    assert result.rationale
    assert result.confidence == 1.0


@pytest.mark.parametrize("instruction", ["Please prepare it for review.", "Do not save yet.", "Preview this before saving."])
def test_explicit_review_request_preserves_unsaved_record_intent(instruction):
    reply = run("I spent $5 on chicken rice yesterday. " + instruction)
    draft = next(r for r in reply.agent_results if r.agent == "spending").data["spending_draft"]
    assert not reply.blocked and draft["action"] == "record"
    assert draft["persistence_intent"] == "preview"
    assert draft["transactions"][0]["amount"] == 5


def test_spend_query_extracts_query_action():
    reply = run("what did I spend on 21/9?")
    result = next(r for r in reply.agent_results if r.agent == "spending")
    draft = result.data["spending_draft"]
    assert draft["action"] == "query"
    assert draft["query_date"] == f"{datetime.now(tz=UTC).date().year}-09-21"


def test_recorded_category_aggregate_selects_supplied_period_without_inventing_a_day():
    reply = run("What is the total recorded dining spend? Answer in one short sentence.",
        requested_agents=["spending"], snapshot={"period_start": "2026-09-01", "recent_transactions": [
            {"description": "Dinner", "category": "dining", "amount": {"amount": 20}, "occurred_on": "2026-09-01"},
            {"description": "Dinner", "category": "dining", "amount": {"amount": 30}, "occurred_on": "2026-09-02"},
        ]})
    draft = next(result for result in reply.agent_results if result.agent == "spending").data["spending_draft"]
    assert draft["action"] == "query" and draft["query_scope"] == "selected_period"
    assert draft["query_categories"] == ["dining"]
    assert draft["query_date"] is None and draft["query_start"] is None and draft["query_end"] is None


def test_undated_lookup_without_scope_and_new_expense_keep_missing_dates():
    reply = run("What is the total recorded dining spend?")
    draft = next(result for result in reply.agent_results if result.agent == "spending").data["spending_draft"]
    assert draft["query_scope"] == "specified" and draft["query_date"] is None
    expense = run("I spent $5 on chicken rice.", snapshot={"period_start": "2026-09-01"})
    record = next(result for result in expense.agent_results if result.agent == "spending").data["spending_draft"]
    assert record["action"] == "record" and record["transactions"][0]["occurred_on"] is None


def test_amount_missing_produces_clarifying_question():
    reply = run("i bought groceries")
    result = next(r for r in reply.agent_results if r.agent == "spending")
    draft = result.data["spending_draft"]
    assert draft["action"] == "record"
    assert draft["transactions"][0]["amount"] is None
    assert draft["transactions"][0]["description"] == "groceries"
    assert draft["questions"]


def test_pending_transaction_continues_extraction():
    reply = run(
        "yesterday",
        pending_transaction={
            "is_spending_request": True,
            "action": "record",
            "persistence_intent": "preview",
            "transactions": [
                {
                    "description": "chicken rice",
                    "amount": 5.0,
                    "category": "dining",
                    "occurred_on": None,
                    "recurring": False,
                    "booking": False,
                }
            ],
            "query_date": None,
            "questions": [],
        },
    )
    result = next(r for r in reply.agent_results if r.agent == "spending")
    draft = result.data["spending_draft"]
    assert draft["action"] == "record"
    assert draft["transactions"][0]["description"] == "chicken rice"
    assert draft["transactions"][0]["amount"] == 5.0
    assert draft["persistence_intent"] == "preview"


def test_spending_analysis_question_is_not_capture():
    reply = run("review my monthly spending patterns")
    spending = next((r for r in reply.agent_results if r.agent == "spending"), None)
    assert spending is None or "spending_draft" not in spending.data


def test_budget_limit_request_is_not_spending_capture():
    reply = run("set budget food: 500, transport: 150, 2026-10, SGD")
    spending = next((r for r in reply.agent_results if r.agent == "spending"), None)
    assert spending is None or "spending_draft" not in spending.data


def test_profile_correction_does_not_resume_pending_transaction():
    reply = run(
        "Actually, it's 4200.",
        pending_transaction={
            "is_spending_request": True, "action": "record",
            "transactions": [{"description": "Dinner", "amount": None}],
        },
        session_context={
            "facts": {"monthly_income": {"value": "4200", "source_position": 3}},
            "last_stated_fields": ["monthly_income"],
        },
    )
    assert not any("spending_draft" in result.data for result in reply.agent_results)
