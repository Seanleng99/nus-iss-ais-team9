from datetime import date

import pytest

from app.api.financial_schemas import BudgetUpsert, GoalCreate
from app.infrastructure.repositories import SQLAlchemyBudgetRepository, SQLAlchemyGoalRepository
from app.services.budget_constraints import AllocationPolicy, DebtCommitment, save_policy
from app.services.budget_tradeoffs import DebtTerms, TradeoffRequest, compare_tradeoffs, simulate
from app.services.budget_workspace import WorkspaceChange, confirm_change, preview_change


def test_interest_and_minimum_rollover_are_explicit():
    debts=[DebtCommitment(name="A",category="debt",balance=100,minimum_payment=100,separate_obligation=True),DebtCommitment(name="B",category="debt",balance=1000,minimum_payment=100,separate_obligation=True)]
    terms={n:DebtTerms(commitment_name=n,annual_rate_percent=12,monthly_fee=0) for n in ["A","B"]}
    rollover=simulate(debts,terms,0,24,True,"Highest interest first")
    released=simulate(debts,terms,0,24,False,"Highest interest first")
    assert rollover["debt_free_month"] < released["debt_free_month"]
    assert rollover["interest"] < released["interest"]
    zero=simulate([debts[0]],{"A":DebtTerms(commitment_name="A",annual_rate_percent=0,monthly_fee=0)},0,1,True,"Smallest balance first")
    assert zero["interest"]==0 and zero["debt_free_month"]==1


def setup(session):
    SQLAlchemyBudgetRepository(session).upsert("u",BudgetUpsert(period_start="2026-10-01",categories=[{"category":"debt","limit_amount":200},{"category":"food","limit_amount":500}],planning={"take_home_income":1500,"savings_target":500}))
    goal=SQLAlchemyGoalRepository(session).create("u",GoalCreate(name="Reserve",target_amount={"amount":1200},target_months=6))
    policy=AllocationPolicy(period_start="2026-10-01",confirmed=True,minimum_savings=0,max_reduction_percent=100,protected_categories=[],category_floors={},goals=[{"goal_id":goal.id,"monthly_amount":200}],debts=[{"name":"Loan","category":"debt","balance":1000,"minimum_payment":200,"separate_obligation":True}])
    save_policy(session,"u",policy)
    return goal


def request():
    return TradeoffRequest(period_start="2026-10-01",terms=[{"commitment_name":"Loan","annual_rate_percent":12,"monthly_fee":0}],cases=[{"name":"Faster repayment","savings_target":400,"extra_debt_payment":400},{"name":"Too much","savings_target":400,"extra_debt_payment":600}],horizon_months=24,rollover_paid_minimums=True)


def test_cases_check_shared_funding_and_never_save(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        report=compare_tradeoffs(session,"u",request())
        assert report["results"][0]["monthly_funded"]
        assert report["results"][1]["funding_gap"]==200
        assert report["results"][0]["goals"][0]["estimated_months"]==6
        preview=preview_change(session,"u",WorkspaceChange(operation="debt_compare",payload_json=request().model_dump_json()))
        assert preview["read_only"]
        with pytest.raises(ValueError,match="cannot be saved"):
            confirm_change(session,"u",preview)
        assert SQLAlchemyBudgetRepository(session).get("u",date(2026,10,1)).planning["savings_target"]==500
        with pytest.raises(ValueError,match="confirmed SGD"):
            compare_tradeoffs(session,"other",request())


def test_missing_terms_and_unallocated_goal_contributions_block_funding(db_session_factory):
    with db_session_factory() as session:
        goal=setup(session)
        req=request()
        req.terms[0].commitment_name="Unknown"
        with pytest.raises(ValueError,match="every saved debt"):
            compare_tradeoffs(session,"u",req)
        req=request()
        req.cases[0].goals=[{"goal_id":goal.id,"monthly_amount":600}]
        req=TradeoffRequest.model_validate(req.model_dump())
        assert compare_tradeoffs(session,"u",req)["results"][0]["savings_allocation_gap"]==200
