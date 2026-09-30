from datetime import date

import pytest

from app.api.financial_schemas import TransactionCreate
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyTransactionRepository,
)
from app.services.budget_reconciliation import (
    MatchRequest,
    match_candidates,
    reconciliation_context,
    save_match,
    save_settings,
)
from app.services.cashflow import CashflowSettings, project_cashflow


def settings(session,kind="expense",category="housing"):
    save_settings(session,"u",CashflowSettings(opening_on="2026-09-01",opening_balance=2000,confirmed=True,schedules=[{"id":"s","name":"Schedule","kind":kind,"category":category,"amount":1000,"first_on":"2026-09-05","frequency":"monthly"}]))


def transaction(session,kind="expense",amount=1000,description="Payment",day="2026-09-05"):
    return SQLAlchemyTransactionRepository(session).create("u",TransactionCreate(description=description,category="housing",amount={"amount":amount},occurred_on=day,transaction_type=kind))


def test_received_income_is_counted_once(db_session_factory):
    with db_session_factory() as session:
        settings(session,"income")
        income=transaction(session,"income")
        assert project_cashflow(session,"u",date(2026,9,30))["closing_balance"]==4000
        save_match(session,"u",MatchRequest(transaction_id=income.id,schedule_id="s",due_on="2026-09-05",amount=1000,effect="income"))
        assert project_cashflow(session,"u",date(2026,9,30))["closing_balance"]==3000


def test_refund_spending_is_explicit_and_in_refund_month(db_session_factory):
    with db_session_factory() as session:
        settings(session)
        payment=transaction(session)
        save_match(session,"u",MatchRequest(transaction_id=payment.id,schedule_id="s",due_on="2026-09-05",amount=1000,effect="payment"))
        refund=transaction(session,"refund",200,day="2026-09-06")
        request=MatchRequest(transaction_id=refund.id,schedule_id="s",due_on="2026-09-05",amount=200,effect="refund_reduces_due")
        with pytest.raises(ValueError,match="Choose whether"):
            save_match(session,"u",request)
        request.spending_treatment="reduce_expense"
        save_match(session,"u",request)
        repo=SQLAlchemyBudgetRepository(session)
        assert repo.spending_by_category("u",date(2026,9,1),currency="SGD")["housing"]==800
        assert sum(float(r["amount"]) for r in repo.review_spending("u",date(2026,9,1),date(2026,9,30)))==800
        assert repo.spending_by_category("other",date(2026,9,1),currency="SGD")=={}


def test_search_pages_and_candidates_are_owned_and_read_only(db_session_factory):
    with db_session_factory() as session:
        settings(session)
        for i in range(101):
            transaction(session,amount=1,description=f"Item {i}")
        target=transaction(session,amount=100,description="Old rent",day="2026-09-03")
        assert reconciliation_context(session,"u")["has_more"]
        assert len(reconciliation_context(session,"u",offset=100)["transactions"])==2
        assert reconciliation_context(session,"u",search="Old rent")["transactions"][0]["id"]==str(target.id)
        suggestions=match_candidates(session,"u",target.id)
        assert suggestions["candidates"][0]["due_on"]=="2026-09-05"
        assert suggestions["candidates"][0]["suggested_amount"]==100
        with pytest.raises(ValueError,match="owned"):
            match_candidates(session,"other",target.id)
        assert reconciliation_context(session,"u")["links"]==[]
