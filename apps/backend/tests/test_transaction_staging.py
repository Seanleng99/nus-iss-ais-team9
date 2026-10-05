from datetime import UTC, date, datetime, timedelta

import pytest
from language_fixtures import language_case

from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
)
from app.services.transaction_staging import (
    handle_transaction_confirmation,
    stage_transaction_draft,
)

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


@pytest.mark.parametrize("bounds,total", [
    ({}, "50.00"), ({"query_date": "2026-08-01"}, "75.00"),
    ({"query_start": "2026-08-01", "query_end": "2026-08-31"}, "75.00"),
    ({"query_all_history": True}, "225.00"),
])
def test_selected_query_scope_preserves_explicit_date_range_and_all_history_priority(db_session_factory, bounds, total):
    from app.api.financial_schemas import TransactionCreate
    from app.services.transaction_staging import SpendingDraft, _answer_query

    with db_session_factory() as session:
        repository = SQLAlchemyTransactionRepository(session)
        for amount, day in [(75, "2026-08-01"), (50, "2026-09-02"), (100, "2026-10-01")]:
            repository.create("selected-u", TransactionCreate(description="Dinner", category="dining",
                amount={"amount": amount}, occurred_on=day))
        draft = SpendingDraft(action="query", query_scope="selected_period", query_categories=["dining"], **bounds)
        answer = _answer_query(session, "selected-u", draft, "Total recorded dining spend.",
                              selected_period_start=date(2026, 9, 1))
        assert f"total SGD {total}" in answer


def test_selected_query_without_trusted_scope_or_with_unresolved_questions_clarifies(db_session_factory):
    from app.services.transaction_staging import SpendingDraft, _answer_query

    with db_session_factory() as session:
        no_scope = SpendingDraft(action="query", query_scope="selected_period")
        unresolved = no_scope.model_copy(update={"questions": ["Which vacation period?"]})
        assert "Which day" in _answer_query(session, "selected-u", no_scope, "Total recorded spend.")
        assert "Which day" in _answer_query(session, "selected-u", unresolved, "Total recorded spend.",
                                           selected_period_start=date(2026, 9, 1))


@pytest.mark.parametrize("include_details", [False, True])
def test_owned_selected_period_total_can_omit_itemized_records(db_session_factory, include_details):
    from app.api.financial_schemas import TransactionCreate
    from app.services.transaction_staging import SpendingDraft, _answer_query

    with db_session_factory() as session:
        repository = SQLAlchemyTransactionRepository(session)
        for amount, day in [(20, "2026-09-01"), (30, "2026-09-02"), (100, "2026-10-01")]:
            repository.create("selected-u", TransactionCreate(description="Dinner", category="dining",
                amount={"amount": amount}, occurred_on=day))
        draft = SpendingDraft(action="query", query_scope="selected_period", query_categories=["dining"],
                              query_include_details=include_details)
        answer = _answer_query(session, "selected-u", draft, "Total recorded dining spend.",
                              selected_period_start=date(2026, 9, 1))
        assert "total SGD 50.00" in answer
        assert "2026-09-01" in answer and "2026-09-30" in answer
        assert ("Dinner" in answer) is include_details
        assert ("\n-" in answer) is include_details
        assert "100.00" not in answer


@pytest.mark.parametrize("confirmation,expected", [("confirm", "saved"), ("cancel", "cancelled"), ("expired", "rejected")])
@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
def test_explicit_ordinary_preview_is_durable_and_only_confirmation_saves(db_session_factory, confirmation, expected, locale):
    items = [
        {"description": "Chicken rice", "amount": 5, "occurred_on": "2026-09-30"},
        {"description": "Tea", "amount": 2, "occurred_on": "2026-09-30"},
    ]
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("preview-u", "preview-chat", "Chat")
        response = draft_response(chat.id, record_draft(persistence_intent="preview", transactions=items))
        response.audit["response_locale"] = locale
        stage_transaction_draft(session, "preview-u", chat, response, "Prepare these expenses for review")
        assert response.audit["action_status"] == "preview"
        assert "Chicken rice" in response.answer and "Tea" in response.answer
        assert "5.00" in response.answer and "2.00" in response.answer
        confirm_command = "confirm transaction" if locale == "en" else language_case("transaction_preview.confirm.zh")
        cancel_command = "cancel transaction" if locale == "en" else language_case("transaction_preview.cancel.zh")
        assert confirm_command in response.answer and cancel_command in response.answer
        assert SQLAlchemyTransactionRepository(session).list_records("preview-u") == []
        assert chat.pending_transaction["draft"]["persistence_intent"] == "preview"
        if confirmation == "expired":
            chat.pending_transaction = {**chat.pending_transaction,
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
        session.commit()
    with db_session_factory() as session:
        assert handle_transaction_confirmation(session, CoachRequest(user_id="other-u", session_id="preview-chat", message="confirm")) is None
        assert handle_transaction_confirmation(session, CoachRequest(user_id="preview-u", session_id="other-chat", message="confirm")) is None
        request = CoachRequest(user_id="preview-u", session_id="preview-chat", message=cancel_command if confirmation == "cancel" else confirm_command)
        response = handle_transaction_confirmation(session, request)
        assert response.audit["action_status"] == expected
        session.commit()
    with db_session_factory() as session:
        rows = SQLAlchemyTransactionRepository(session).list_records("preview-u")
        assert len(rows) == (2 if confirmation == "confirm" else 0)
        if rows:
            assert {float(row.amount) for row in rows} == {5, 2}
            assert all(row.recurrence is None and not row.recurring for row in rows)
        assert handle_transaction_confirmation(session, request) is None


@pytest.mark.parametrize("interlude", ["unrelated", "not_spending", "query", "unresolved_query", "forecast"])
@pytest.mark.parametrize("expired", [False, True])
def test_explicit_preview_survives_read_only_turns_without_extending_approval(db_session_factory, interlude, expired):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("preview-u", "preview-chat", "Chat")
        draft = record_draft(persistence_intent="preview", transactions=[
            {"description": "Rice", "amount": 5, "occurred_on": "2026-09-30"},
        ])
        stage_transaction_draft(session, "preview-u", chat, draft_response(chat.id, draft), "Prepare this for review")
        if expired:
            chat.pending_transaction = {**chat.pending_transaction,
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
        original = dict(chat.pending_transaction)
        if interlude == "unrelated":
            reply = CoachResponse(session_id=chat.id, selected_agents=["investment_education"],
                answer="Educational answer", agent_results=[], disclaimers=[], audit={})
        else:
            next_draft = {
                "not_spending": {"is_spending_request": False},
                "query": query_draft(query_date="2026-09-30"),
                "unresolved_query": query_draft(),
                "forecast": {"action": "forecast", "query_start": "2026-10-01", "query_end": "2026-10-31"},
            }[interlude]
            reply = draft_response(chat.id, next_draft)
        stage_transaction_draft(session, "preview-u", chat, reply, "Read-only question")
        assert chat.pending_transaction == original
        if interlude == "unresolved_query":
            assert "still pending" in reply.answer and "restate" in reply.answer
        assert SQLAlchemyTransactionRepository(session).list_records("preview-u") == []
        session.commit()
    with db_session_factory() as session:
        result = handle_transaction_confirmation(session, CoachRequest(user_id="preview-u", session_id="preview-chat", message="confirm"))
        assert result.audit["action_status"] == ("rejected" if expired else "saved")
        assert len(SQLAlchemyTransactionRepository(session).list_records("preview-u")) == (0 if expired else 1)


def test_preview_amendment_remains_unsaved_when_extractor_defaults_to_save(db_session_factory):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("preview-u", "preview-chat", "Chat")
        original = record_draft(persistence_intent="preview", transactions=[
            {"description": "Rice", "amount": 5, "occurred_on": "2026-09-30"},
        ])
        stage_transaction_draft(session, "preview-u", chat, draft_response(chat.id, original), "Prepare this for review")
        corrected = record_draft(transactions=[
            {"description": "Rice", "amount": 7, "occurred_on": "2026-09-30"},
        ])
        response = draft_response(chat.id, corrected)
        stage_transaction_draft(session, "preview-u", chat, response, "The amount was 7")
        assert response.audit["action_status"] == "preview"
        assert "7.00" in response.answer
        assert SQLAlchemyTransactionRepository(session).list_records("preview-u") == []
        assert chat.pending_transaction["draft"]["persistence_intent"] == "preview"
        confirmed = handle_transaction_confirmation(session, CoachRequest(user_id="preview-u", session_id="preview-chat", message="confirm"))
        assert confirmed.audit["action_status"] == "saved"
        assert float(SQLAlchemyTransactionRepository(session).list_records("preview-u")[0].amount) == 7


def test_preview_missing_details_never_saves_complete_sibling(db_session_factory):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("preview-u", "preview-chat", "Chat")
        response = draft_response(chat.id, record_draft(persistence_intent="preview", transactions=[
            {"description": "Rice", "amount": 5, "occurred_on": "2026-09-30"},
            {"description": "Tea", "amount": None, "occurred_on": "2026-09-30"},
        ]))
        stage_transaction_draft(session, "preview-u", chat, response, "Prepare these for review")
        assert response.audit["action_status"] == "needs_input"
        assert SQLAlchemyTransactionRepository(session).list_records("preview-u") == []
        assert chat.pending_transaction["draft"]["persistence_intent"] == "preview"
        assert handle_transaction_confirmation(session, CoachRequest(user_id="preview-u", session_id="preview-chat", message="confirm")).audit["action_status"] == "no_pending"
        assert SQLAlchemyTransactionRepository(session).list_records("preview-u") == []


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
        assert "no matching" in reply.answer.lower()
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
        assert "2026-10-03" in followup.answer.lower()
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
        assert "2026-09-01 – 2026-09-30" in reply.answer.lower()
        assert chat.pending_transaction is None


def test_period_query_with_no_records_names_the_period(db_session_factory) -> None:
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u1", "sc-s6", "Chat")
        reply = draft_response("sc-s6", query_draft())
        stage_transaction_draft(session, "u1", chat, reply, "what did i spend last month")
        session.commit()
        assert "no matching" in reply.answer.lower()
        assert "2026-09-01 – 2026-09-30" in reply.answer.lower()
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
        assert "2026-10-03" in followup.answer.lower()
        assert chat.pending_transaction is None
