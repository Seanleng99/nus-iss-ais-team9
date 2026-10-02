from datetime import date

import pytest

from app.domain.schemas import CoachResponse
from app.infrastructure.repositories import SQLAlchemyChatRepository
from app.services.transaction_staging import stage_transaction_draft

TODAY = date(2026, 10, 1)


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import transaction_capture as capture

    monkeypatch.setattr(capture, "_today", lambda: TODAY)


def draft_response(session_id: str, draft: dict) -> CoachResponse:
    return CoachResponse(
        session_id=session_id,
        selected_agents=["spending"],
        answer="draft",
        disclaimers=[],
        audit={},
        agent_results=[{"agent": "spending", "summary": "Draft", "data": {"spending_draft": draft}}],
    )


def query_draft(**updates) -> dict:
    return {
        "is_spending_request": True,
        "action": "query",
        "query_date": None,
        "transactions": [],
        "questions": [],
        **updates,
    }


def record_draft(**updates) -> dict:
    return {
        "is_spending_request": True,
        "action": "record",
        "query_date": None,
        "questions": [],
        "transactions": [
            {
                "description": "skincare",
                "amount": None,
                "category": None,
                "occurred_on": "2026-10-01",
                "recurring": False,
                "booking": False,
            }
        ],
        **updates,
    }


def test_resolved_query_clears_stale_record_draft(db_session_factory) -> None:
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s1", "Chat")
        stage_transaction_draft(
            session, "u1", chat, draft_response("sc-s1", record_draft()),
            "i have spent 20 on skincare today",
        )
        session.commit()
        assert chat.pending_transaction is not None
        reply = draft_response("sc-s1", query_draft(query_date="2026-10-03"))
        stage_transaction_draft(
            session, "u1", chat, reply, "what transactions do i have on the 3rd Oct"
        )
        session.commit()
        assert chat.pending_transaction is None
        assert "no transactions" in reply.answer.lower()
        assert reply.audit["spending_capture"] == "read_only_query"


def test_unresolved_query_keeps_pending_and_followup_date_resolves(db_session_factory) -> None:
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s2", "Chat")
        reply = draft_response("sc-s2", query_draft())
        stage_transaction_draft(
            session, "u1", chat, reply, "can you tell me what transactions do i have"
        )
        session.commit()
        assert "which day" in reply.answer.lower()
        assert chat.pending_transaction is not None
        assert chat.pending_transaction["draft"]["action"] == "query"
        assert reply.audit["spending_capture"] == "needs_input"
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).get("u1", "sc-s2")
        followup = draft_response("sc-s2", chat.pending_transaction["draft"])
        stage_transaction_draft(session, "u1", chat, followup, "3rd Oct")
        session.commit()
        assert "3 october 2026" in followup.answer.lower()
        assert chat.pending_transaction is None


def test_month_period_query_lists_the_whole_month(db_session_factory) -> None:
    from app.api.financial_schemas import TransactionCreate
    from app.domain.schemas import ApplicationMoneyAmount
    from app.infrastructure.repositories import SQLAlchemyTransactionRepository

    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s4", "Chat")
        SQLAlchemyTransactionRepository(session).create(
            "u1",
            TransactionCreate(
                description="Lunch",
                category="food",
                amount=ApplicationMoneyAmount(amount=12.0),
                occurred_on=date(2026, 10, 1),
            ),
        )
        SQLAlchemyTransactionRepository(session).create(
            "u1",
            TransactionCreate(
                description="Kopi",
                category="food",
                amount=ApplicationMoneyAmount(amount=2.0),
                occurred_on=date(2026, 10, 2),
            ),
        )
        session.commit()
        reply = draft_response("sc-s4", query_draft())
        stage_transaction_draft(
            session, "u1", chat, reply, "what transactions do i have for this month"
        )
        session.commit()
        assert "lunch" in reply.answer.lower()
        assert "kopi" in reply.answer.lower()
        assert "14.00" in reply.answer
        assert "which day" not in reply.answer.lower()
        assert chat.pending_transaction is None
        assert reply.audit["spending_capture"] == "read_only_query"


def test_last_month_period_query(db_session_factory) -> None:
    from app.api.financial_schemas import TransactionCreate
    from app.domain.schemas import ApplicationMoneyAmount
    from app.infrastructure.repositories import SQLAlchemyTransactionRepository

    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s5", "Chat")
        SQLAlchemyTransactionRepository(session).create(
            "u1",
            TransactionCreate(
                description="MRT top-up",
                category="transport",
                amount=ApplicationMoneyAmount(amount=10.0),
                occurred_on=date(2026, 9, 15),
            ),
        )
        SQLAlchemyTransactionRepository(session).create(
            "u1",
            TransactionCreate(
                description="Lunch",
                category="food",
                amount=ApplicationMoneyAmount(amount=12.0),
                occurred_on=date(2026, 10, 1),
            ),
        )
        session.commit()
        reply = draft_response("sc-s5", query_draft())
        stage_transaction_draft(session, "u1", chat, reply, "what did i spend last month")
        session.commit()
        assert "mrt top-up" in reply.answer.lower()
        assert "lunch" not in reply.answer.lower()
        assert "september 2026" in reply.answer.lower()
        assert chat.pending_transaction is None


def test_period_query_with_no_records_names_the_period(db_session_factory) -> None:
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s6", "Chat")
        reply = draft_response("sc-s6", query_draft())
        stage_transaction_draft(session, "u1", chat, reply, "what did i spend last month")
        session.commit()
        assert "no transactions" in reply.answer.lower()
        assert "september 2026" in reply.answer.lower()
        assert chat.pending_transaction is None


def test_period_falls_back_to_day_question_when_unmatched(db_session_factory) -> None:
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s7", "Chat")
        reply = draft_response("sc-s7", query_draft())
        stage_transaction_draft(session, "u1", chat, reply, "what transactions do i have")
        session.commit()
        assert "which day" in reply.answer.lower()
        assert chat.pending_transaction is not None


def test_followup_date_with_the_prefix_resolves(db_session_factory) -> None:
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s3", "Chat")
        reply = draft_response("sc-s3", query_draft())
        stage_transaction_draft(
            session, "u1", chat, reply, "can you tell me what transactions do i have"
        )
        session.commit()
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).get("u1", "sc-s3")
        followup = draft_response("sc-s3", chat.pending_transaction["draft"])
        stage_transaction_draft(session, "u1", chat, followup, "the 3rd Oct")
        session.commit()
        assert "3 october 2026" in followup.answer.lower()
        assert chat.pending_transaction is None
