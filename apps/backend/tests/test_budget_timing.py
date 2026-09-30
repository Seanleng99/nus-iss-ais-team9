from datetime import date

from app.api.financial_schemas import BudgetPlanSettings
from app.services.budget_timing import TimingSettings, assess_timing
from app.services.financial_workspace import write_section


def setup(session, pattern="even_daily", opening=1000):
    write_section(session, "u", "cashflow", {"opening_on":"2026-10-01", "opening_balance":opening, "confirmed":True,
        "schedules":[{"id":"rent", "name":"Rent", "category":"housing", "kind":"expense", "amount":1500,"first_on":"2026-10-05","frequency":"monthly"},
                     {"id":"pay", "name":"Salary", "category":"salary", "kind":"income", "amount":3000,"first_on":"2026-10-20","frequency":"monthly"}]})
    timing = TimingSettings(period_start="2026-10-01",start_on="2026-10-01",minimum_balance=100,expense_pattern=pattern,savings_on="2026-10-21",records_complete=True,confirmed=True)
    write_section(session,"u","timing:2026-10-01",timing.model_dump(mode="json"))


def assess(session, income=3000, food=500, owner="u"):
    return assess_timing(session,owner,date(2026,10,1),{"housing":1500,"food":food},BudgetPlanSettings(take_home_income=income,savings_target=500),today=date(2026,10,1))


def test_monthly_affordable_but_short_before_payday(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        result=assess(session)
        assert result["status"] == "shortfall"
        assert result["first_below_buffer_on"] == "2026-10-05"
        assert result["lowest_available"] < -500
        assert result["days"][-1]["projected_available"] == 1500
        assert result["unpaid_bills"] == 1500
        assert assess(session, owner="other")["status"] == "needs_input"


def test_timing_and_reductions_change_shortfall_without_moving_bills(db_session_factory):
    with db_session_factory() as session:
        setup(session, "end_of_period", opening=1600)
        result=assess(session)
        assert result["status"] == "within_buffer"
        setup(session,"start_of_period", opening=1600)
        assert assess(session)["buffer_gap"] == 500
        assert assess(session,food=200)["buffer_gap"] == 200
        assert assess(session, income=3200)["status"] == "needs_input"


def test_stale_timing_and_spent_limits_require_clarification(db_session_factory):
    from app.api.financial_schemas import TransactionCreate
    from app.infrastructure.repositories import SQLAlchemyTransactionRepository
    with db_session_factory() as session:
        setup(session)
        SQLAlchemyTransactionRepository(session).create("u",TransactionCreate(description="Food",category="food",amount={"amount":700},occurred_on="2026-10-01"))
        result=assess(session)
        assert result["status"] == "needs_input"
        assert any("food" in q for q in result["questions"])
        result=assess_timing(session,"u",date(2026,10,1),{},BudgetPlanSettings(take_home_income=3000,savings_target=500),today=date(2026,10,2))
        assert result["status"] == "needs_input" and not result["days"]
