from datetime import date

import pytest

from app.api.financial_schemas import BudgetUpsert
from app.infrastructure.repositories import SQLAlchemyBudgetRepository
from app.services.budget_constraints import constraint_questions
from app.services.budget_continuity import (
    BatchConfirmation,
    ContinuityRequest,
    confirm_batch,
    preview_batch,
)
from app.services.budget_income import IncomeScenarios, compare_income
from app.services.budget_reserves import Reserves, reserve_report
from app.services.financial_workspace import write_section


def setup(session):
    SQLAlchemyBudgetRepository(session).upsert("u",BudgetUpsert(period_start="2026-09-01",categories=[{"category":"food","limit_amount":500}],planning={"take_home_income":2000,"savings_target":500}))


def test_distinct_months_and_limits_preview_then_atomic_save(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        request=ContinuityRequest(source_period="2026-09-01",first_period="2026-10-01",months=2,carry_rule="copy_limits",month_inputs=[
            {"period_start":"2026-10-01","take_home_income":1000,"savings_target":100},
            {"period_start":"2026-11-01","take_home_income":1800,"savings_target":300,"category_limits":{"food":700}}])
        preview=preview_batch(session,"u",request,today=date(2026,9,30))
        assert preview["ready"]
        assert [r["unallocated"] for r in preview["plans"]]==[400,800]
        confirm_batch(session,"u",BatchConfirmation(preview_id=preview["preview_id"],confirmed=True),today=date(2026,9,30))
        assert SQLAlchemyBudgetRepository(session).get("u",date(2026,11,1)).planning["take_home_income"]==1800
        with pytest.raises(ValueError,match="every month"):
            ContinuityRequest(source_period="2026-09-01",first_period="2026-10-01",months=2,carry_rule="copy_limits",month_inputs=request.month_inputs[:1])


def test_income_cases_keep_limits_and_do_not_write(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        result=compare_income(session,"u",IncomeScenarios(period_start="2026-09-01",low=800,expected=1200,high=1600))
        assert [r["totals"]["funding_gap"] for r in result["results"]]==[0,200,0,0]
        assert SQLAlchemyBudgetRepository(session).get("u",date(2026,9,1)).planning["take_home_income"]==2000
        with pytest.raises(ValueError,match="confirmed SGD"):
            compare_income(session,"other",IncomeScenarios(period_start="2026-09-01",low=800,expected=1200,high=1600))


def test_reserves_share_savings_even_without_policy(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        settings=Reserves(confirmed=True,reserves=[{"name":"Annual fee","target_amount":1200,"current_reserved":0,"monthly_contribution":300,"start_period":"2026-09-01","due_on":"2026-12-20"}])
        report=reserve_report(settings,date(2026,9,1))
        assert report["reserves"][0]["required_monthly"]==300
        assert report["reserves"][0]["projected_gap"]==0
        write_section(session,"u","reserves",settings.model_dump(mode="json"))
        from app.api.financial_schemas import BudgetPlanSettings
        assert constraint_questions(session,"u",date(2026,10,1),{"food":500},BudgetPlanSettings(take_home_income=2000,savings_target=200))
        assert not constraint_questions(session,"u",date(2027,1,1),{"food":500},BudgetPlanSettings(take_home_income=2000,savings_target=200))
