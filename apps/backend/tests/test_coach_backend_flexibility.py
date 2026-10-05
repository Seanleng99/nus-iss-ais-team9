from datetime import date

import pytest
from coach_i18n import translate
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.financial_schemas import TransactionCreate
from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import AgentName, AgentResult, CoachRequest, CoachResponse, SourceCitation
from app.infrastructure.models import CoachActionStateRecord, TransactionRecord
from app.infrastructure.repositories import (
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyUserRepository,
)
from app.main import app
from app.services.budget_alert import parse_budget_status_query
from app.services.recurring_forecast import handle_recurring_forecast_query
from app.services.transaction_capture import classify_category, handle_transaction_capture
from app.services.transaction_staging import SpendingDraft, _answer_query, stage_transaction_draft

TODAY = date(2026, 10, 1)
HEADERS = {"X-API-Key": settings.api_key}


@pytest.fixture(autouse=True)
def freeze_today(monkeypatch):
    monkeypatch.setattr("app.services.transaction_capture._today", lambda: TODAY)


def add(session, description="Lunch", amount=12, when="2026-10-01", category="food", user="coach-u", **kwargs):
    return SQLAlchemyTransactionRepository(session).create(user, TransactionCreate(
        description=description, amount={"amount": amount}, occurred_on=when,
        category=category, **kwargs,
    ))


def draft_response(chat_id, draft, locale="en"):
    return CoachResponse(session_id=chat_id, selected_agents=["spending"], answer="Generated draft",
        agent_results=[{"agent": "spending", "summary": "Draft", "data": {"spending_draft": draft}}],
        disclaimers=[], audit={"response_locale": locale})


@pytest.mark.parametrize("message", [
    "Am I on track to reach my emergency fund goal?", "How am I doing?",
    "Explain what over budget means", "Is my retirement goal on track?",
])
def test_budget_status_requires_its_subject(message):
    assert not parse_budget_status_query(message)


def test_snapshot_preserves_selected_period_history_and_separate_recurring(db_session_factory):
    with db_session_factory() as session:
        add(session, "Previous August", when="2026-08-01")
        add(session, "Selected September", when="2026-09-02")
        add(session, "Later October", when="2026-10-02")
        add(session, "Older recurring annual bill", when="2025-01-01", recurring=True)
        add(session, "Income", when="2026-09-01", transaction_type="income")
        add(session, "Other user's secret", when="2026-09-01", user="other-u")
        snapshot = SQLAlchemyUserRepository(session).get_financial_snapshot("coach-u", date(2026, 9, 1))
        assert snapshot.period_start == "2026-09-01"
        assert [x.description for x in snapshot.recent_transactions] == ["Selected September"]
        assert [x.description for x in snapshot.historical_transactions] == ["Previous August"]
        assert [x.description for x in snapshot.recurring_expenses] == ["Older recurring annual bill"]
        assert snapshot.transaction_context["records_complete"] is False
        assert snapshot.transaction_context["recurring_cadence_known"] is False


def test_lookup_week_crosses_month_and_year_includes_december(db_session_factory):
    with db_session_factory() as session:
        add(session, "September entry", when="2026-09-30", amount=5)
        add(session, "October entry", when="2026-10-01", amount=7)
        add(session, "January entry", when="2025-01-03", amount=11)
        add(session, "December entry", when="2025-12-29", amount=13)
        draft = SpendingDraft(action="query")
        week = _answer_query(session, "coach-u", draft, "this week")
        assert "September entry" in week and "October entry" in week and "12.00" in week
        year = _answer_query(session, "coach-u", draft, "last year")
        assert "January entry" in year and "December entry" in year and "24.00" in year


def test_filtered_range_lookup_honors_all_fields_and_owned_expenses(db_session_factory):
    with db_session_factory() as session:
        add(session, "Cafe Lunch", amount=12, when="2026-08-01")
        add(session, "Cafe Coffee", amount=3, when="2026-09-02")
        add(session, "Cafe Ride", amount=20, when="2026-09-03", category="transport")
        add(session, "Cafe Salary", amount=15, transaction_type="income")
        add(session, "Cafe Other User", amount=19, user="other-u")
        draft = SpendingDraft(action="query", query_start="2026-08-01", query_end="2026-09-30",
            query_categories=["food"], query_description="cafe", query_min_amount=5, query_max_amount=15,
            query_group_by="category")
        answer = _answer_query(session, "coach-u", draft, "all cafe food between August and September")
        assert "1 matching" in answer and "12.00" in answer
        assert "Coffee" not in answer and "Salary" not in answer
        assert "food: SGD 12.00" in answer


def test_lookup_detail_limit_does_not_limit_total(db_session_factory):
    with db_session_factory() as session:
        for index in range(60):
            add(session, description=f"Recorded meal {index}", amount=10)
        answer = _answer_query(session, "coach-u", SpendingDraft(action="query", query_all_history=True), "all dates")
        assert "60 matching" in answer and "600.00" in answer
        assert "Showing 50 of 60" in answer
        assert answer.count("Recorded meal") == 50


def test_description_filter_uses_literal_percent(db_session_factory):
    with db_session_factory() as session:
        add(session, "50% Cafe", amount=5)
        add(session, "50 Cafe", amount=7)
        answer = _answer_query(session, "coach-u", SpendingDraft(action="query", query_all_history=True,
            query_description="50%"), "the literal merchant name")
        assert "1 matching" in answer and "50% Cafe" in answer and "5.00" in answer


def test_recurring_excludes_income_preserves_distinct_names_and_unknown_cadence(db_session_factory):
    with db_session_factory() as session:
        add(session, "Netflix", amount=18, recurring=True, when="2026-09-01")
        add(session, "Netflix", amount=15, recurring=True, when="2026-08-01")
        add(session, "Netflix Kids", amount=7, recurring=True)
        add(session, "Annual insurance", amount=1200, recurring=True)
        add(session, "Monthly salary", amount=5000, recurring=True, transaction_type="income")
        answer = handle_recurring_forecast_query(session, "coach-u", "coach-c").answer
        # Without a stable obligation identity, identical legacy descriptions
        # may be separate bills and cannot safely be deduplicated.
        assert "1240.00" in answer and "Netflix Kids" in answer
        assert "Netflix SGD 18.00" in answer and "Netflix SGD 15.00" in answer
        assert "Monthly salary" not in answer
        assert "not a monthly total or a forecast" in answer


def test_durable_delete_requires_same_conversation_and_consumes_once(db_session_factory):
    with db_session_factory() as session:
        record_id = add(session).id
        session.commit()
        preview = handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-a", message="delete lunch"))
        assert "confirm" in preview.answer
        session.commit()
    with db_session_factory() as session:
        unrelated = handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-b", message="confirm"))
        assert unrelated is None
        assert session.get(TransactionRecord, record_id) is not None
    with db_session_factory() as session:
        deleted = handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-a", message="confirm"))
        assert deleted.answer.startswith("Deleted:")
        session.commit()
    with db_session_factory() as session:
        assert handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-a", message="confirm")) is None
        assert session.get(TransactionRecord, record_id) is None
        assert session.get(CoachActionStateRecord, "chat-a").pending_edit is None


def test_stale_delete_baseline_requires_new_preview(db_session_factory):
    with db_session_factory() as session:
        record_id = add(session).id
        session.commit()
        handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-a", message="delete lunch"))
        session.commit()
    with db_session_factory() as session:
        session.get(TransactionRecord, record_id).amount = 22
        session.commit()
    with db_session_factory() as session:
        reply = handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-a", message="confirm"))
        assert "fresh preview" in reply.answer and "22.00" in reply.answer
        assert session.get(TransactionRecord, record_id) is not None


def test_last_saved_amendment_is_durable_and_conversation_scoped(db_session_factory):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("coach-u", "chat-a", "Chat")
        response = draft_response(chat.id, {"transactions": [{"description": "Lunch", "amount": 12, "occurred_on": "2026-10-01"}]})
        stage_transaction_draft(session, "coach-u", chat, response, "I spent 12 on lunch today")
        session.commit()
    with db_session_factory() as session:
        assert handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-b", message="actually 22")) is None
        own = handle_transaction_capture(session, CoachRequest(user_id="coach-u", session_id="chat-a", message="actually 22"))
        assert own.answer.startswith("Updated:") and "22.00" in own.answer
        session.commit()


def test_category_fallback_does_not_match_word_substrings():
    assert classify_category("baggage fee") == "other"
    assert classify_category("business insurance") == "other"
    assert classify_category("bus ticket") == "transport"
    assert classify_category("hand bag") == "shopping"


def test_staged_spending_acknowledgement_uses_selected_language(db_session_factory):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("coach-u", "chat-zh", "Chat")
        response = draft_response(chat.id, {"transactions": [{"description": "Lunch", "amount": 12, "occurred_on": "2026-10-01"}]}, "zh-Hans")
        stage_transaction_draft(session, "coach-u", chat, response, "I spent 12 on lunch today")
        expected_item = translate("coach_action.saved_item", "zh-Hans", description="Lunch", amount="12.00", date="2026-10-01", category="Food")
        assert response.answer == translate("coach_action.saved", "zh-Hans", items=expected_item)


def test_bulk_capture_rolls_back_every_item_on_second_failure(db_session_factory, monkeypatch):
    original = SQLAlchemyTransactionRepository.create
    calls = []
    def fail_second(self, *args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise SQLAlchemyError("synthetic write failure")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(SQLAlchemyTransactionRepository, "create", fail_second)
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("coach-u", "chat-bulk", "Chat")
        session.commit()
        response = draft_response(chat.id, {"transactions": [
            {"description": "Lunch", "amount": 12, "occurred_on": "2026-10-01"},
            {"description": "Tea", "amount": 3, "occurred_on": "2026-10-01"}]})
        stage_transaction_draft(session, "coach-u", chat, response, "log lunch and tea today")
        assert session.scalar(select(func.count()).select_from(TransactionRecord)) == 0
        assert "Saved:" not in response.answer
        assert chat.pending_transaction is not None


def test_validated_backend_result_keeps_provenance_for_next_turn_context(db_session_factory, monkeypatch):
    class SemanticStatusAI:
        async def coach(self, request):
            return CoachResponse(session_id=request.session_id, selected_agents=["budget"],
                answer="A reviewed preliminary response", agent_results=[], disclaimers=[],
                audit={"reviewed_response": True, "turn_decision": {"budget_status_query": True}})
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: SemanticStatusAI())
    with TestClient(app) as client:
        response = client.post("/api/coach", headers=HEADERS, json={
            "user_id": "coach-u", "session_id": "local-chat", "message": "Am I over budget?"})
        assert response.status_code == 200
        answer = response.json()["answer"]
    with db_session_factory() as session:
        _, _, context = SQLAlchemyChatRepository(session).context_snapshot("coach-u", "local-chat")
        assert context[-1]["content"] == answer
        assert "answer_status" not in context[-1]


def test_mixed_capture_preserves_reviewed_education_and_renders_approved_citation(monkeypatch):
    class FakeAI:
        async def coach(self, request):
            response = draft_response(request.session_id, {"transactions": [
                {"description": "Lunch", "amount": 12, "occurred_on": "2026-10-01"}]})
            response.selected_agents.append(AgentName.INVESTMENT_EDUCATION)
            response.agent_results.append(AgentResult(agent="investment_education", summary="Diversification spreads exposure. [source:moneysense-etf]"))
            response.sources.append(SourceCitation(source_id="moneysense-etf", title="ETF guide", issuing_organization="MoneySense",
                canonical_url="https://www.moneysense.gov.sg/guide-to-etfs/", published_at="2026-01-01"))
            return response
    fake = FakeAI()
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: fake)
    with TestClient(app) as client:
        body = client.post("/api/coach", headers=HEADERS, json={"user_id": "coach-u", "session_id": "mixed-chat",
            "message": "Log lunch today and explain diversification"}).json()
    assert "Saved:" in body["answer"] and "Diversification spreads exposure" in body["answer"]
    assert "[source:" not in body["answer"]
    assert "[ETF guide](https://www.moneysense.gov.sg/guide-to-etfs/)" in body["answer"]

@pytest.mark.parametrize('change', ['currency', 'transaction_type'])
def test_currency_or_type_change_invalidates_pending_delete(db_session_factory, change):
    with db_session_factory() as session:
        record_id = add(session).id
        session.commit()
        handle_transaction_capture(session, CoachRequest(user_id='coach-u', session_id='guard-chat', message='delete lunch'))
        session.commit()
    with db_session_factory() as session:
        setattr(session.get(TransactionRecord, record_id), change, 'USD' if change == 'currency' else 'income')
        session.commit()
    with db_session_factory() as session:
        reply = handle_transaction_capture(session, CoachRequest(user_id='coach-u', session_id='guard-chat', message='confirm'))
        assert 'no longer an SGD expense' in reply.answer
        assert session.get(TransactionRecord, record_id) is not None


def test_action_consume_rolls_back_with_its_write(db_session_factory):
    with db_session_factory() as session:
        record_id = add(session).id
        session.commit()
        handle_transaction_capture(session, CoachRequest(user_id='coach-u', session_id='atomic-chat', message='delete lunch'))
        session.commit()
    with db_session_factory() as session:
        handle_transaction_capture(session, CoachRequest(user_id='coach-u', session_id='atomic-chat', message='confirm'))
        session.rollback()
    with db_session_factory() as session:
        assert session.get(TransactionRecord, record_id) is not None
        assert session.get(CoachActionStateRecord, 'atomic-chat').pending_edit is not None
        handle_transaction_capture(session, CoachRequest(user_id='coach-u', session_id='atomic-chat', message='confirm'))
        session.commit()
        assert session.get(TransactionRecord, record_id) is None


def test_chat_deletion_cascades_private_action_references(db_session_factory):
    with db_session_factory() as session:
        add(session)
        session.commit()
        handle_transaction_capture(session, CoachRequest(user_id='coach-u', session_id='delete-chat', message='delete lunch'))
        session.commit()
        SQLAlchemyChatRepository(session).delete('coach-u', 'delete-chat')
        session.commit()
        assert session.get(CoachActionStateRecord, 'delete-chat') is None


def test_action_state_migration_round_trip(db_session_factory):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    path = Path(__file__).resolve().parents[1] / 'migrations/versions/20261004_0016_coach_action_states.py'
    spec = importlib.util.spec_from_file_location('action_state_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with db_session_factory() as session:
        connection = session.connection()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert 'coach_action_states' not in inspect(connection).get_table_names()
            migration.upgrade()
            assert {column['name'] for column in inspect(connection).get_columns('coach_action_states')} == {
                'session_id', 'user_id', 'last_saved', 'pending_edit', 'created_at', 'updated_at'}


def test_filtered_date_follow_up_does_not_use_bare_day_shortcut(monkeypatch):
    class FakeAI:
        def __init__(self):
            self.calls = 0
        async def coach(self, request):
            self.calls += 1
            fields = {'query_date': '2026-09-20'} if self.calls == 1 else {
                'query_date': '2026-09-21', 'query_categories': ['food']}
            return draft_response(request.session_id, {'action': 'query', **fields})
    fake = FakeAI()
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: fake)
    with TestClient(app) as client:
        first = client.post('/api/coach', headers=HEADERS, json={'user_id': 'coach-u', 'session_id': 'filtered-chat', 'message': 'What did I spend on20/9?'})
        assert first.status_code == 200
        second = client.post('/api/coach', headers=HEADERS, json={'user_id': 'coach-u', 'session_id': 'filtered-chat', 'message': 'What about food on21/9?'})
        assert second.status_code == 200
        assert fake.calls == 2, second.json().get("audit")
        assert second.json()['audit']['spending_capture'] == 'read_only_query'
        assert second.json()['audit'].get('source') != 'spending_date_query'

@pytest.mark.parametrize('message', [
    "My wife's income is SGD5000. Help us size an emergency fund.",
    "Our partner's monthly expenses are 2000. Explain household budgeting.",
    "Compare our contributions: my spouse income is SGD2000.",
    "Help budget with my spouse income SGD2000.",
    "I spent SGD100 on an iPhone15 today.",
    "How much did I spend on20/9?",
    "Show my expenses at Cafe123 on20/9.",
    "Show expenses for Cafe123.",
])
def test_provided_household_values_product_tokens_and_dates_are_not_private_lookups(message):
    from app.services.privacy_guard import find_other_user_reference
    assert find_other_user_reference(message, 'coach-u') is None


def test_supplied_value_does_not_authorize_private_household_lookup():
    from app.services.privacy_guard import find_other_user_reference
    assert find_other_user_reference("Show my wife's income is SGD5000 from her account", 'coach-u') is not None


def test_filtered_query_then_bare_date_continues_through_semantic_extraction(monkeypatch):
    class FakeAI:
        def __init__(self):
            self.calls = 0
        async def coach(self, request):
            self.calls += 1
            return draft_response(request.session_id, {'action': 'query',
                'query_date': '2026-09-20' if self.calls == 1 else '2026-09-21',
                'query_categories': ['food'], 'query_min_amount': 20})
    fake = FakeAI()
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: fake)
    with TestClient(app) as client:
        for message in ('How much food spending over20 did I record on 20/9?', 'What about21/9?'):
            # Correct spacing lets the compatibility grammar resolve a bare day;
            # the preceding filters must still require semantic extraction.
            message = message.replace('about21', 'about 21')
            reply = client.post('/api/coach', headers=HEADERS, json={'user_id': 'coach-u', 'session_id': 'filtered-context', 'message': message})
            assert reply.status_code == 200
        assert fake.calls == 2
        assert reply.json()['audit']['spending_capture'] == 'read_only_query'
        assert reply.json()['audit'].get('source') != 'spending_date_query'
