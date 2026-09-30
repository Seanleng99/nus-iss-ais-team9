"""Deterministic, read-only debt/goal trade-offs using explicit terms and funding."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.services.budget_constraints import (
    AllocationPolicy,
    GoalContribution,
    Money,
    cents,
    constraint_questions,
    linked_goals,
)
from app.services.financial_workspace import read_section


class DebtTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commitment_name: str = Field(min_length=1,max_length=100)
    annual_rate_percent: float = Field(ge=0,le=300,allow_inf_nan=False)
    monthly_fee: Money


class AllocationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1,max_length=60)
    savings_target: Money
    extra_debt_payment: Money
    goals: list[GoalContribution] | None = Field(default=None,max_length=50)


class TradeoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    terms: list[DebtTerms] = Field(min_length=1,max_length=50)
    cases: list[AllocationCase] = Field(min_length=1,max_length=3)
    horizon_months: int = Field(ge=1,le=360)
    rollover_paid_minimums: bool


def simulate(debts, terms, extra, horizon, rollover, strategy):
    balances={d.name:cents(d.balance) for d in debts}
    minimums={d.name:cents(d.minimum_payment) for d in debts}
    original_pool=sum(minimums.values())+cents(extra)
    interest=fees=paid=0
    timeline=[]
    paid_off={name:0 for name,balance in balances.items() if not balance}
    for month in range(1,horizon+1):
        if not any(balances.values()):
            break
        active=[name for name,balance in balances.items() if balance]
        pool=original_pool if rollover else sum(minimums[n] for n in active)+cents(extra)
        for name in active:
            term=terms[name]
            charge=int((Decimal(balances[name])*Decimal(str(term.annual_rate_percent))/1200).quantize(Decimal(1),rounding=ROUND_HALF_UP))
            fee=cents(term.monthly_fee)
            interest+=charge
            fees+=fee
            balances[name]+=charge+fee
            payment=min(minimums[name],balances[name])
            balances[name]-=payment
            pool-=payment
            paid+=payment
        order=sorted(active,key=lambda n:(-terms[n].annual_rate_percent,n)) if strategy=="Highest interest first" else sorted(active,key=lambda n:(balances[n],n))
        for name in order:
            payment=min(max(pool,0),balances[name])
            balances[name]-=payment
            pool-=payment
            paid+=payment
            if not balances[name] and name not in paid_off:
                paid_off[name]=month
        timeline.append({"month":month,"balance":sum(balances.values())/100})
    return {"strategy":strategy,"interest":interest/100,"fees":fees/100,"total_repaid":paid/100,
            "remaining_balance":sum(balances.values())/100,"debt_free_month":max(paid_off.values(),default=0) if not any(balances.values()) else None,
            "paid_off_months":paid_off,"timeline":timeline}


def compare_tradeoffs(session,user_id,request):
    from app.api.financial_schemas import BudgetPlanSettings
    from app.infrastructure.repositories import SQLAlchemyBudgetRepository
    from app.services.budget_reserves import reserve_requirement
    if request.period_start.day!=1:
        raise ValueError("Choose the first day of a planning month")
    record=SQLAlchemyBudgetRepository(session).get(user_id,request.period_start)
    raw=read_section(session,user_id,"constraints:"+str(request.period_start))
    if not record or not record.planning or record.currency!="SGD" or not raw:
        raise ValueError("Save a confirmed SGD plan and debt commitments first")
    policy=AllocationPolicy.model_validate(raw["policy"])
    names=[d.name for d in policy.debts]
    terms={t.commitment_name:t for t in request.terms}
    if not names or len(set(names))!=len(names) or len(terms)!=len(request.terms) or set(terms)!=set(names):
        raise ValueError("Give each debt a unique name and supply explicit rates and fees for every saved debt, including zero")
    categories={c.category:float(c.limit_amount) for c in record.categories}
    from app.services.budget_constraints import requirements
    floors = (requirements(session, user_id, request.period_start) or {}).get("floors", {})
    expenses=sum(max(cents(categories.get(name, 0)), floors.get(name, 0)) for name in categories.keys() | floors.keys())
    income=cents(record.planning["take_home_income"])
    results=[]
    for case in request.cases:
        chosen=policy.model_copy(update={"goals":case.goals if case.goals is not None else policy.goals})
        if len({g.goal_id for g in chosen.goals})!=len(chosen.goals):
            raise ValueError("Choose each goal once per case")
        goals=linked_goals(session,user_id,chosen)
        savings_required=sum(cents(g.monthly_amount) for g in chosen.goals)+reserve_requirement(session,user_id,request.period_start)
        gap=max(expenses+cents(case.extra_debt_payment)+cents(case.savings_target)-income,0)
        savings_gap=max(savings_required-cents(case.savings_target),0)
        planning=BudgetPlanSettings.model_validate({**record.planning,"savings_target":case.savings_target})
        questions=constraint_questions(session,user_id,request.period_start,categories,planning)
        results.append({"name":case.name,"savings_target":case.savings_target,"extra_debt_payment":case.extra_debt_payment,
            "funding_gap":gap/100,"savings_allocation_gap":savings_gap/100,"monthly_funded":not gap and not savings_gap,
            "requires_commitment_changes":questions,"goals":goals,
            "strategies":[simulate(policy.debts,terms,case.extra_debt_payment,request.horizon_months,request.rollover_paid_minimums,strategy) for strategy in ["Highest interest first","Smallest balance first"]]})
    return {"results":results,"read_only":True,"warnings":[
        "Monthly illustration using nominal annual rate divided by 12, interest rounded to cents, explicit fixed monthly fees and end-of-month payments. No new borrowing, rate changes, penalties, tax or daily compounding are assumed. Confirm these assumptions match the terms you want to compare.",
        "Extra repayment uses only the displayed monthly allocation; minimum payments already belong to expense limits. Goal contributions and irregular-cost reserves share savings. Unfunded cases are not affordable plans.",
        "No actual balances, contributions, commitments or budgets change. Goal dates assume constant contributions without investment returns. Dates/within-month cash availability require a separate timing assessment."]}


def describe_tradeoffs(result):
    lines=["Debt and goal comparison — no changes have been saved."]
    for case in result["results"]:
        lines.append(f"{case['name']}: savings SGD {case['savings_target']:,.2f}, extra debt payment SGD {case['extra_debt_payment']:,.2f}; funding gap SGD {case['funding_gap']:,.2f}; savings allocation gap SGD {case['savings_allocation_gap']:,.2f}.")
        for s in case["strategies"]:
            lines.append(f"{s['strategy']}: interest SGD {s['interest']:,.2f}, fees SGD {s['fees']:,.2f}, debt-free month {s['debt_free_month'] if s['debt_free_month'] is not None else 'outside the chosen horizon'}, remaining SGD {s['remaining_balance']:,.2f}.")
        for g in case["goals"]:
            lines.append(f"Goal {g['name']}: SGD {g['monthly_amount']:,.2f}/month; estimated completion in {g['estimated_months'] if g['estimated_months'] is not None else 'unknown'} months.")
        lines.extend(case["requires_commitment_changes"])
    lines.extend(result["warnings"])
    return "\n\n".join(lines)
