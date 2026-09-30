import json
from datetime import date

import pytest

from app.api.financial_schemas import BudgetUpsert, TransactionCreate
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyTransactionRepository,
)
from app.services.budget_history import AdaptiveRequest, adaptive_review, history
from app.services.budget_workspace import WorkspaceChange, confirm_change, preview_change


def save(session,period,limit):
    return SQLAlchemyBudgetRepository(session).upsert("u",BudgetUpsert(period_start=period,categories=[{"category":"food","limit_amount":limit}],planning={"take_home_income":3000,"savings_target":500}))


def test_versions_record_changes_only_and_restore_as_new_version(db_session_factory):
    with db_session_factory() as session:
        save(session,"2026-10-01",500)
        original=history(session,"u",date(2026,10,1))[0]
        save(session,"2026-10-01",700)
        save(session,"2026-10-01",700)
        assert len(history(session,"u",date(2026,10,1)))==2
        preview=preview_change(session,"u",WorkspaceChange(operation="restore",payload_json=json.dumps({"period_start":"2026-10-01","version_id":original["id"]})))
        assert preview["details"]["proposed"]["categories"][0]["limit_amount"]==500
        assert SQLAlchemyBudgetRepository(session).get("u",date(2026,10,1)).categories[0].limit_amount==700
        confirm_change(session,"u",preview)
        assert len(history(session,"u",date(2026,10,1)))==3
        assert history(session,"other",date(2026,10,1))==[]


def test_restore_stale_preview_does_not_overwrite_new_plan(db_session_factory):
    with db_session_factory() as session:
        save(session,"2026-10-01",500)
        original=history(session,"u",date(2026,10,1))[0]
        preview=preview_change(session,"u",WorkspaceChange(operation="restore",payload_json=json.dumps({"period_start":"2026-10-01","version_id":original["id"]})))
        save(session,"2026-10-01",900)
        with pytest.raises(ValueError,match="changed"):
            confirm_change(session,"u",preview)


def test_adaptive_requires_repeated_observations_and_never_writes(db_session_factory):
    with db_session_factory() as session:
        for month,spent in [(7,700),(8,900),(9,300)]:
            save(session,date(2026,month,1),500)
            SQLAlchemyTransactionRepository(session).create("u",TransactionCreate(description="Food",category="food",amount={"amount":spent},occurred_on=date(2026,month,10)))
        save(session,"2026-10-01",500)
        result=adaptive_review(session,"u",AdaptiveRequest(period_start="2026-10-01",lookback_months=3),today=date(2026,10,1))
        assert result["suggestions"][0]["suggested_limit"]==633.34
        assert result["suggestions"][0]["overrun_months"]==2
        assert len(history(session,"u",date(2026,10,1)))==1
        with pytest.raises(ValueError,match="SGD"):
            adaptive_review(session,"other",AdaptiveRequest(period_start="2026-10-01"),today=date(2026,10,1))
