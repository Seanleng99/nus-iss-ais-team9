from datetime import date

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
    assert draft["transactions"][0]["amount"] == 5.0
    assert draft["transactions"][0]["description"] == "chicken rice"
    assert "unsaved" in result.summary
    assert result.rationale
    assert result.confidence == 1.0


def test_spend_query_extracts_query_action():
    reply = run("what did I spend on 21/9?")
    result = next(r for r in reply.agent_results if r.agent == "spending")
    draft = result.data["spending_draft"]
    assert draft["action"] == "query"
    assert draft["query_date"] == f"{date.today().year}-09-21"


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


def test_spending_analysis_question_is_not_capture():
    reply = run("review my monthly spending patterns")
    spending = next((r for r in reply.agent_results if r.agent == "spending"), None)
    assert spending is None or "spending_draft" not in spending.data


def test_budget_limit_request_is_not_spending_capture():
    reply = run("set budget food: 500, transport: 150, 2026-10, SGD")
    spending = next((r for r in reply.agent_results if r.agent == "spending"), None)
    assert spending is None or "spending_draft" not in spending.data
