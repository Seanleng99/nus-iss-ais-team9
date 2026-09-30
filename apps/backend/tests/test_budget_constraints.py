from datetime import date

import pytest

from app.api.financial_schemas import BudgetUpsert, GoalCreate
from app.domain.schemas import CoachResponse
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyChatRepository,
    SQLAlchemyGoalRepository,
)
from app.services.budget_capture import BudgetDraft, _preview, stage_budget_draft
from app.services.budget_constraints import (
    AllocationPolicy,
    AlternativesRequest,
    build_alternatives,
    requirements,
    save_policy,
)
from app.services.financial_workspace import write_section

PERIOD = date(2026, 10, 1)


def setup(session, **overrides):
    payload = BudgetUpsert(
        period_start=PERIOD,
        categories=[
            {"category": "housing", "limit_amount": 1500},
            {"category": "fun", "limit_amount": 1000},
        ],
        planning={"take_home_income": 3000, "savings_target": 500},
    )
    SQLAlchemyBudgetRepository(session).upsert("u", payload)
    policy = AllocationPolicy(
        period_start=PERIOD,
        confirmed=True,
        minimum_savings=500,
        max_reduction_percent=50,
        protected_categories=["housing"],
        category_floors={},
        goals=[],
        debts=[],
    )
    policy = AllocationPolicy.model_validate({**policy.model_dump(), **overrides})
    save_policy(session, "u", policy)
    return payload


def test_funded_alternatives_protect_minimums_and_do_not_write(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        result = build_alternatives(
            session, "u", AlternativesRequest(period_start=PERIOD, take_home_income=2700)
        )
        for item in result["results"][1:]:
            assert item["fits_income"]
            assert {c["category"]: c["limit_amount"] for c in item["draft"]["categories"]} == {
                "housing": 1500,
                "fun": 700,
            }
        record = SQLAlchemyBudgetRepository(session).get("u", PERIOD)
        assert record.planning["take_home_income"] == 3000
        assert sum(float(c.limit_amount) for c in record.categories) == 2500
        assert not build_alternatives(session, "other", AlternativesRequest(period_start=PERIOD))[
            "results"
        ]


def test_infeasible_plan_exposes_gap_and_maximum_cut(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        result = build_alternatives(
            session, "u", AlternativesRequest(period_start=PERIOD, take_home_income=2000)
        )
        for item in result["results"][1:]:
            assert not item["fits_income"]
            assert item["totals"]["funding_gap"] == 500


def test_scheduled_bills_and_debt_floor_are_not_added_twice(db_session_factory):
    with db_session_factory() as session:
        write_section(
            session,
            "u",
            "cashflow",
            {
                "opening_on": "2026-10-01",
                "opening_balance": 0,
                "confirmed": True,
                "schedules": [
                    {
                        "id": "loan-bill",
                        "name": "Loan bill",
                        "category": "fun",
                        "kind": "expense",
                        "amount": 650,
                        "first_on": "2026-10-15",
                        "frequency": "monthly",
                    }
                ],
            },
        )
        setup(session, debts=[{"name": "Loan", "category": "fun", "balance": 5000,
                              "minimum_payment": 650, "schedule_id": "loan-bill"}])
        assert requirements(session, "u", PERIOD)["floors"]["fun"] == 65000


def test_goal_contributions_share_savings_and_owner_is_checked(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        repo = SQLAlchemyGoalRepository(session)
        goals = [
            repo.create(
                "u",
                GoalCreate(
                    name=name,
                    target_amount={"amount": 3000},
                    current_amount={"amount": 0},
                    target_months=10,
                ),
            )
            for name in ["A", "B"]
        ]
        policy = AllocationPolicy(
            period_start=PERIOD,
            confirmed=True,
            minimum_savings=100,
            max_reduction_percent=100,
            protected_categories=[],
            category_floors={},
            debts=[],
            goals=[{"goal_id": g.id, "monthly_amount": 300} for g in goals],
        )
        save_policy(session, "u", policy)
        result = build_alternatives(session, "u", AlternativesRequest(period_start=PERIOD))
        assert result["commitments"]["savings"] == 600
        assert all(g["estimated_months"] == 10 for g in result["commitments"]["goals"])
        policy.goals[0].goal_id = repo.create(
            "other", GoalCreate(name="Other", target_amount={"amount": 100}, target_months=1)
        ).id
        with pytest.raises(ValueError, match="belonging"):
            save_policy(session, "u", policy)


def test_repository_and_coach_cannot_bypass_protection(db_session_factory):
    with db_session_factory() as session:
        payload = setup(session)
        payload.categories[0].limit_amount = 1000
        with pytest.raises(ValueError, match="housing"):
            SQLAlchemyBudgetRepository(session).upsert("u", payload)
        data = payload.model_dump(mode="json", exclude={"review_evidence"})
        data["planning"].pop("version")
        preview, baseline = _preview(session, "u", BudgetDraft.model_validate(data))
        assert baseline is None and "housing" in preview
        payload.categories = []
        with pytest.raises(ValueError, match="housing"):
            SQLAlchemyBudgetRepository(session).upsert("u", payload)


def test_coach_alternatives_are_read_only_and_use_stored_comparison(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        chat = SQLAlchemyChatRepository(session).create("u", "s", "Budget")
        response = CoachResponse(
            session_id="s",
            selected_agents=["budget"],
            answer="draft",
            agent_results=[
                {
                    "agent": "budget",
                    "summary": "draft",
                    "data": {
                        "budget_draft": {
                            "action": "alternatives",
                            "period_start": PERIOD.isoformat(),
                        }
                    },
                }
            ],
            disclaimers=[],
            audit={},
        )
        stage_budget_draft(session, "u", chat, response)
        assert "Proportional reductions" in response.answer
        assert not chat.pending_budget["ready"]
        assert len(chat.pending_budget["comparison"]["results"]) == 3
