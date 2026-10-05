import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from coach_math.recurrence import next_occurrence, occurrence_dates
from fastapi.testclient import TestClient
from language_fixtures import language_case
from pydantic import ValidationError
from sqlalchemy import func, inspect, select

from app.api.financial_schemas import TransactionCreate
from app.core.config import settings
from app.domain.recurrence import LedgerRecurrence
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.models import TransactionRecord
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyUserRepository,
)
from app.main import app
from app.services.cashflow import CashflowSettings, Schedule
from app.services.financial_workspace import write_section
from app.services.recurring_forecast import recurring_expense_forecast
from app.services.transaction_capture import handle_transaction_capture
from app.services.transaction_staging import (
    handle_transaction_confirmation,
    stage_transaction_draft,
)


def expense(session, name="Rent", amount=100, *, user="recurrence-u", when="2026-01-31", **extra):
    return SQLAlchemyTransactionRepository(session).create(user, TransactionCreate(
        description=name, category="housing", amount={"amount": amount}, occurred_on=when, **extra))


def monthly():
    return {"frequency": "monthly", "first_on": "2026-01-31", "next_due_on": "2026-02-28"}


@pytest.mark.parametrize("terms,start,end,expected", [
    (monthly(), "2026-02-01", "2026-04-30", ["2026-02-28", "2026-03-31", "2026-04-30"]),
    ({"frequency": "monthly", "month_end": True, "first_on": "2026-04-30", "next_due_on": "2026-05-31"},
     "2026-05-01", "2026-08-31", ["2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31"]),
    ({"frequency": "monthly", "first_on": "2026-04-30", "next_due_on": "2026-05-30"},
     "2026-05-01", "2026-08-31", ["2026-05-30", "2026-06-30", "2026-07-30", "2026-08-30"]),
    ({"frequency": "monthly", "interval": 2, "first_on": "2026-01-31", "next_due_on": "2026-03-31"},
     "2026-03-01", "2026-09-30", ["2026-03-31", "2026-05-31", "2026-07-31", "2026-09-30"]),
    ({"frequency": "weekly", "first_on": "2026-01-31", "next_due_on": "2026-02-07"},
     "2026-02-01", "2026-02-28", ["2026-02-07", "2026-02-14", "2026-02-21", "2026-02-28"]),
    ({"frequency": "fortnightly", "first_on": "2026-01-31", "next_due_on": "2026-02-14"},
     "2026-02-01", "2026-02-28", ["2026-02-14", "2026-02-28"]),
    ({"frequency": "yearly", "first_on": "2024-02-29", "next_due_on": "2025-02-28"},
     "2025-02-01", "2028-03-01", ["2025-02-28", "2026-02-28", "2027-02-28", "2028-02-29"]),
    ({"frequency": "yearly", "interval": 2, "first_on": "2024-02-29", "next_due_on": "2026-02-28"},
     "2025-01-01", "2028-03-01", ["2026-02-28", "2028-02-29"]),
])
def test_calendar_anchor_intervals_and_leap_years(terms, start, end, expected):
    rule = LedgerRecurrence.model_validate(terms)
    assert [d.isoformat() for d in occurrence_dates(rule, date.fromisoformat(start), date.fromisoformat(end))] == expected
    assert next_occurrence(rule, date.fromisoformat(expected[0])).isoformat() == expected[1]
    schedule = Schedule(id="bill", name="Rent", category="housing", kind="expense", amount=100, **terms)
    assert occurrence_dates(schedule, date.fromisoformat(start), date.fromisoformat(end)) == occurrence_dates(rule, date.fromisoformat(start), date.fromisoformat(end))


@pytest.mark.parametrize("changes", [
    {"interval": 0}, {"interval": 121}, {"interval": True}, {"interval": 1.5},
    {"frequency": "daily"}, {"next_due_on": "2026-03-30"}, {"last_on": "2026-01-01"},
    {"next_due_on": "2026-01-31"},
])
def test_invalid_or_already_paid_schedule_is_rejected(changes):
    with pytest.raises(ValidationError):
        TransactionCreate(description="Rent", category="housing", amount={"amount": 100},
                          occurred_on="2026-01-31", recurrence={**monthly(), **changes})


def test_same_name_obligations_stay_distinct_and_explicit_identity_updates_terms(db_session_factory):
    with db_session_factory() as session:
        a = expense(session, amount=100, recurrence=monthly())
        b = expense(session, amount=200, recurrence=monthly())
        assert a.obligation_id != b.obligation_id
        expense(session, amount=150, when="2026-02-28", obligation_id=a.obligation_id,
                recurrence={**monthly(), "next_due_on": "2026-03-31"})
        data = recurring_expense_forecast(session, "recurrence-u", date(2026, 3, 1), date(2026, 3, 31))
        assert data["total"] == 350 and data["occurrence_count"] == 2
        assert {x["obligation_id"] for x in data["occurrences"]} == {a.obligation_id, b.obligation_id}


def test_forecast_totals_use_actual_calendar_occurrences_and_exclude_income_currency_and_other_users(db_session_factory):
    with db_session_factory() as session:
        expense(session, amount=100, recurrence=monthly())
        expense(session, "Weekly fee", amount=10, recurrence={"frequency": "weekly", "first_on": "2026-01-31", "next_due_on": "2026-02-07"})
        expense(session, "Annual bill", amount=1200, when="2024-02-29", recurrence={"frequency": "yearly", "first_on": "2024-02-29", "next_due_on": "2025-02-28"})
        expense(session, "Secret", amount=999, user="other-u", recurrence=monthly())
        salary = expense(session, "Income", amount=5000, recurrence=monthly())
        salary.transaction_type = "income"
        foreign = expense(session, "Foreign", amount=999, recurrence=monthly())
        foreign.currency = "USD"
        data = recurring_expense_forecast(session, "recurrence-u", date(2026, 2, 1), date(2026, 2, 28))
        assert data["total"] == 1340 and data["occurrence_count"] == 6
        assert {x["description"] for x in data["occurrences"]} == {"Rent", "Weekly fee", "Annual bill"}


def test_legacy_flags_do_not_invent_cadence_or_merge_identical_descriptions(db_session_factory):
    with db_session_factory() as session:
        expense(session, amount=100, recurring=True)
        expense(session, amount=200, recurring=True)
        data = recurring_expense_forecast(session, "recurrence-u", date(2026, 2, 1), date(2026, 2, 28))
        assert data["total"] == 0 and data["schedule_count"] == 0
        assert data["unknown_cadence_count"] == 2 and data["unknown_recorded_total"] == 300


def test_workspace_schedule_identity_does_not_double_count_ledger_and_honors_settlement(db_session_factory):
    with db_session_factory() as session:
        config = CashflowSettings(opening_on="2026-01-01", opening_balance=0, confirmed=True, schedules=[
            Schedule(id="rent", name="Rent", category="housing", kind="expense", amount=100,
                     first_on="2026-01-31", frequency="monthly", settled_dates=[date(2026, 3, 31)]),
            Schedule(id="income", name="Salary", category="income", kind="income", amount=5000,
                     first_on="2026-01-31", frequency="monthly"),
        ])
        write_section(session, "recurrence-u", "cashflow", config.model_dump(mode="json"))
        expense(session, obligation_id="rent", recurrence=monthly())
        feb = recurring_expense_forecast(session, "recurrence-u", date(2026, 2, 1), date(2026, 2, 28))
        mar = recurring_expense_forecast(session, "recurrence-u", date(2026, 3, 1), date(2026, 3, 31))
        assert feb["total"] == 100 and feb["occurrence_count"] == 1
        assert mar["total"] == 0 and mar["occurrence_count"] == 0


def test_linked_bill_amount_edit_stays_gated_without_server_error(db_session_factory):
    with db_session_factory() as session:
        config = CashflowSettings(opening_on="2026-01-01", opening_balance=0, confirmed=True, schedules=[
            Schedule(id="rent", name="Rent", category="housing", kind="expense", amount=100,
                     first_on="2026-01-31", frequency="monthly")])
        write_section(session, "recurrence-u", "cashflow", config.model_dump(mode="json"))
        row = expense(session, obligation_id="rent", recurrence=monthly())
        request = CoachRequest(user_id="recurrence-u", session_id="linked-edit", message="change rent to SGD120")
        assert "confirm" in handle_transaction_capture(session, request).answer.lower()
        response = handle_transaction_capture(session, request.model_copy(update={"message": "confirm"}))
        assert "Nothing was changed" in response.answer and row.amount == 100


def stage(session, locale="en", cadence=None):
    chat = SQLAlchemyChatRepository(session).get_for_update("recurrence-u", "recurrence-chat")
    if chat is None:
        chat = SQLAlchemyChatRepository(session).create("recurrence-u", "recurrence-chat", "Coach")
    response = CoachResponse(session_id=chat.id, selected_agents=["spending"], answer="Draft",
        agent_results=[{"agent": "spending", "summary": "Draft", "data": {"spending_draft": {
            "action": "record", "transactions": [{"description": "Rent", "amount": 100,
            "occurred_on": "2026-01-31", "recurrence": cadence or {"frequency": "monthly"}}]}}}],
        disclaimers=[], audit={"response_locale": locale})
    stage_transaction_draft(session, "recurrence-u", chat, response, "I paid monthly rent SGD100 on 2026-01-31")
    return chat, response


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
def test_supplied_frequency_requires_durable_owned_confirmation_and_preserves_anchor(db_session_factory, monkeypatch, locale):
    monkeypatch.setattr("app.services.transaction_capture._today", lambda: date(2026, 1, 31))
    command = "confirm transaction" if locale == "en" else language_case("transaction_preview.confirm.zh")
    with db_session_factory() as session:
        _chat, response = stage(session, locale)
        assert response.audit["spending_capture"] == "awaiting_confirmation"
        assert response.audit["action_status"] == "preview"
        assert "2026-02-28" in response.answer
        assert command in response.answer
        assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 0
        session.commit()
    with db_session_factory() as session:
        assert handle_transaction_confirmation(session, CoachRequest(user_id="recurrence-u", session_id="other-chat", message="confirm")) is None
        answer = handle_transaction_confirmation(session, CoachRequest(user_id="recurrence-u", session_id="recurrence-chat", message=command))
        assert answer is not None and "100.00" in answer.answer
        assert "2026-02-28" in answer.answer and "2026-01-31" in answer.answer
        assert answer.audit["confirmed_recurrences"][0]["recurrence"]["frequency"] == "monthly"
        assert answer.audit["confirmed_recurrences"][0]["recurrence"]["next_due_on"] == "2026-02-28"
        assert answer.audit["action_status"] == "saved"
        session.commit()
    with db_session_factory() as session:
        row = session.scalar(select(TransactionRecord))
        assert row.recurrence["first_on"] == "2026-01-31" and row.recurrence["next_due_on"] == "2026-02-28"
        assert row.obligation_id and row.recurring
        assert handle_transaction_confirmation(session, CoachRequest(user_id="recurrence-u", session_id="recurrence-chat", message="confirm")) is None


@pytest.mark.parametrize("cancel", [False, True])
def test_cancelled_or_expired_preview_never_writes(db_session_factory, monkeypatch, cancel):
    monkeypatch.setattr("app.services.transaction_capture._today", lambda: date(2026, 1, 31))
    with db_session_factory() as session:
        chat, _ = stage(session)
        if not cancel:
            chat.pending_transaction = {**chat.pending_transaction, "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
        response = handle_transaction_confirmation(session, CoachRequest(user_id="recurrence-u", session_id=chat.id, message="cancel" if cancel else "confirm"))
        assert response.audit["action_status"] == ("cancelled" if cancel else "rejected")
        assert chat.pending_transaction is None
        assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 0


def test_invalid_cadence_preview_blocks_confirmation(db_session_factory, monkeypatch):
    monkeypatch.setattr("app.services.transaction_capture._today", lambda: date(2026, 1, 31))
    with db_session_factory() as session:
        chat, response = stage(session, cadence={**monthly(), "next_due_on": "2026-03-30"})
        assert response.audit["spending_capture"] == "invalid_recurrence"
        assert chat.pending_transaction is None
        assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 0


def test_named_amount_edit_preserves_recurrence_and_rechecks_changed_schedule(db_session_factory):
    with db_session_factory() as session:
        row = expense(session, recurrence=monthly())
        request = CoachRequest(user_id="recurrence-u", session_id="edit-chat", message="change rent to SGD120")
        preview = handle_transaction_capture(session, request)
        assert "confirm" in preview.answer.lower()
        row.recurrence = {**row.recurrence, "next_due_on": "2026-03-31"}
        refreshed = handle_transaction_capture(session, request.model_copy(update={"message": "confirm"}))
        assert "changed" in refreshed.answer and row.amount == 100
        handle_transaction_capture(session, request.model_copy(update={"message": "confirm"}))
        assert row.amount == 120 and row.recurrence["next_due_on"] == "2026-03-31"


def test_api_identity_export_delete_and_invalid_owner(db_session_factory):
    headers = {"X-API-Key": settings.api_key}
    payload = {"description": "Rent", "category": "housing", "amount": {"amount": 100},
               "occurred_on": "2026-01-31", "recurrence": monthly()}
    with TestClient(app) as client:
        response = client.post("/api/users/recurrence-u/transactions", headers=headers, json=payload)
        assert response.status_code == 201
        row = response.json()
        assert row["recurring"] and row["obligation_id"] and row["recurrence"]["next_due_on"] == "2026-02-28"
        rejected = client.post("/api/users/other-u/transactions", headers=headers,
                               json={**payload, "obligation_id": row["obligation_id"]})
        assert rejected.status_code == 422
        exported = client.get("/api/users/recurrence-u/data-export", headers=headers).json()["data"]["transactions"][0]
        assert exported["recurrence"] == row["recurrence"] and exported["obligation_id"] == row["obligation_id"]
        assert client.delete("/api/users/recurrence-u/transactions/" + row["id"], headers=headers).status_code == 204
    with db_session_factory() as session:
        assert recurring_expense_forecast(session, "recurrence-u", date(2026, 2, 1), date(2026, 2, 28))["total"] == 0


def test_user_erasure_covers_schedule_terms_and_identity(db_session_factory):
    with db_session_factory() as session:
        expense(session, recurrence=monthly())
        exported = SQLAlchemyUserRepository(session).export_user_data("recurrence-u")
        assert exported["transactions"][0]["obligation_id"]
        SQLAlchemyUserRepository(session).delete_user_data("recurrence-u")
        assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 0


def test_migration_round_trip_preserves_legacy_unknown_and_index(db_session_factory):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/20261004_0017_explicit_transaction_recurrence.py"
    spec = importlib.util.spec_from_file_location("recurrence_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261004_0016"
    with db_session_factory() as session:
        record_id = expense(session, recurring=True).id
        session.commit()
        with session.bind.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert "recurrence" not in {column["name"] for column in inspect(connection).get_columns("transactions")}
            migration.upgrade()
            assert "ix_transactions_user_obligation" in {index["name"] for index in inspect(connection).get_indexes("transactions")}
        session.expire_all()
        legacy = session.get(TransactionRecord, record_id)
        assert legacy.recurring and legacy.recurrence is None and legacy.obligation_id is None


def test_typed_forecast_preserves_filters_range_and_read_only_behavior(db_session_factory):
    with db_session_factory() as session:
        expense(session, "Rent", amount=100, recurrence=monthly())
        expense(session, "Rent parking", amount=20, recurrence=monthly())
        chat = SQLAlchemyChatRepository(session).create("recurrence-u", "forecast-chat", "Coach")
        reply = CoachResponse(session_id=chat.id, selected_agents=["spending"], answer="Generated",
            agent_results=[{"agent": "spending", "summary": "Forecast", "data": {"spending_draft": {
                "action": "forecast", "query_start": "2026-02-01", "query_end": "2026-03-31",
                "query_categories": ["housing"], "query_description": "rent", "min_amount": 50,
                "max_amount": 150}}}], disclaimers=[], audit={"response_locale": "zh-Hans"})
        before = session.scalar(select(func.count()).select_from(TransactionRecord))
        stage_transaction_draft(session, "recurrence-u", chat, reply, "forecast rent expenses")
        assert reply.audit["spending_capture"] == "read_only_forecast"
        assert reply.audit["recurring_forecast"]["total"] == 200
        assert "2026-02-01" in reply.answer and "2026-03-31" in reply.answer and "200.00" in reply.answer
        assert session.scalar(select(func.count()).select_from(TransactionRecord)) == before
        assert chat.pending_transaction is None


def test_forecast_detail_cap_retains_nearest_dates_and_exact_total(db_session_factory):
    with db_session_factory() as session:
        expense(session, "Weekly", amount=10, recurrence={"frequency": "weekly", "first_on": "2026-01-31", "next_due_on": "2026-02-07"})
        expense(session, "Monthly", amount=100, recurrence=monthly())
        data = recurring_expense_forecast(session, "recurrence-u", date(2026, 2, 1), date(2029, 1, 31))
        expected_weekly = len(occurrence_dates({"frequency": "weekly", "first_on": "2026-01-31", "next_due_on": "2026-02-07"}, date(2026, 2, 1), date(2029, 1, 31)))
        assert data["occurrence_count"] == expected_weekly + 36
        assert data["total"] == expected_weekly * 10 + 3600
        assert data["details_truncated"] and len(data["occurrences"]) == 100
        assert {x["description"] for x in data["occurrences"]} == {"Weekly", "Monthly"}
        assert data["occurrences"] == sorted(data["occurrences"], key=lambda x: (x["due_on"], x["description"], x["obligation_id"]))
