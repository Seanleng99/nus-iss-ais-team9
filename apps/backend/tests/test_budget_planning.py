from datetime import date

import pytest
from pydantic import ValidationError

from app.api.financial_schemas import BudgetUpsert, ProfileUpsert, TransactionCreate
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyUserRepository,
)
from app.services.budget_capture import handle_budget_confirmation, stage_budget_draft
from app.services.budget_planning import build_planning_context

PERIOD = date(2026, 10, 1)


def planning_draft(**updates):
    result = {
        "period_start": PERIOD.isoformat(),
        "currency": "SGD",
        "categories": [
            {"category": "housing", "limit_amount": 2700},
            {"category": "hobbies", "limit_amount": 700},
        ],
        "planning": {
            "take_home_income": 4000,
            "income_basis": "take_home",
            "savings_target": 800,
            "expenses_confirmed": True,
        },
    }
    result.update(updates)
    return result


def stage(session, draft):
    chats = SQLAlchemyChatRepository(session)
    chat = chats.get("u1", "plan") or chats.create("u1", "plan", "Planning")
    response = CoachResponse(
        session_id="plan",
        selected_agents=["budget"],
        answer="draft",
        agent_results=[
            {
                "agent": "budget",
                "summary": "draft",
                "data": {"budget_draft": draft, "planning_analysis": {"funding_gap": 0}},
            }
        ],
        disclaimers=[],
        audit={},
    )
    stage_budget_draft(session, "u1", chat, response)
    session.commit()
    return response


def confirm(session, message="confirm budget"):
    return handle_budget_confirmation(
        session, CoachRequest(user_id="u1", session_id="plan", message=message)
    )


def test_shortfall_is_recomputed_not_trusted_from_ai_and_blocks_confirmation(db_session_factory):
    with db_session_factory() as session:
        response = stage(session, planning_draft())
        assert "Funding gap: SGD 200.00" in response.answer
        assert "Funding gap" in confirm(session).answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None
        assert confirm(session, "yes") is None  # Clarification, not a save instruction.


def test_corrected_plan_saves_income_and_savings_separately(db_session_factory):
    with db_session_factory() as session:
        stage(session, planning_draft())
        response = stage(
            session,
            planning_draft(
                categories=[
                    {"category": "housing", "limit_amount": 2700},
                    {"category": "hobbies", "limit_amount": 500},
                ]
            ),
        )
        assert "Unallocated income: SGD 0.00" in response.answer
        assert "confirm budget" in response.answer
        assert confirm(session).answer.startswith("Saved")
        session.commit()
        record = SQLAlchemyBudgetRepository(session).get("u1", PERIOD)
        assert record.planning["take_home_income"] == 4000
        assert record.planning["savings_target"] == 800
        assert sum(float(item.limit_amount) for item in record.categories) == 3200
        assert all(item.category != "savings" for item in record.categories)


@pytest.mark.parametrize(
    "updates,question",
    [
        ({"take_home_income": None}, "take-home income"),
        ({"income_basis": "gross"}, "take-home income"),
        ({"savings_target": None}, "set aside in savings"),
        ({"expenses_confirmed": False}, "debt payments and irregular costs"),
    ],
)
def test_missing_planning_inputs_cannot_be_confirmed(db_session_factory, updates, question):
    with db_session_factory() as session:
        draft = planning_draft()
        draft["planning"].update(updates)
        assert question in stage(session, draft).answer
        assert question in confirm(session).answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None


def test_existing_limits_are_included_in_affordability(db_session_factory):
    with db_session_factory() as session:
        repository = SQLAlchemyBudgetRepository(session)
        repository.upsert(
            "u1",
            BudgetUpsert(
                period_start=PERIOD,
                categories=[
                    {"category": "housing", "limit_amount": 3000},
                ],
            ),
        )
        response = stage(
            session, planning_draft(categories=[{"category": "food", "limit_amount": 500}])
        )
        assert "Funding gap: SGD 300.00" in response.answer
        assert "Existing category limits kept" in response.answer
        assert "Funding gap" in confirm(session).answer


def test_planning_cannot_be_downgraded_to_capture_to_bypass_shortfall(db_session_factory):
    with db_session_factory() as session:
        stage(session, planning_draft())
        response = stage(session, planning_draft(planning=None))
        assert "cannot be skipped" in response.answer
        assert "Funding gap" in confirm(session).answer


def test_snapshot_aggregates_only_owned_sgd_closed_months_without_recurring_duplication(
    db_session_factory,
):
    with db_session_factory() as session:
        SQLAlchemyUserRepository(session).upsert_profile(
            "u1", ProfileUpsert(monthly_income={"amount": 4000})
        )
        repository = SQLAlchemyTransactionRepository(session)
        for user, when, value, currency, recurring in [
            ("u1", "2026-08-15", 100, "SGD", True),
            ("u1", "2026-08-16", 20, "SGD", False),
            ("u1", "2026-09-01", 999, "SGD", False),
            ("u1", "2026-08-15", 888, "USD", False),
            ("u2", "2026-08-15", 777, "SGD", False),
        ]:
            repository.create(
                user,
                TransactionCreate(
                    description="Example",
                    category="food",
                    occurred_on=when,
                    amount={"amount": value, "currency": currency},
                    recurring=recurring,
                ),
            )
        context = build_planning_context(session, "u1", today=date(2026, 9, 29))
        assert context["recorded_spending"] == [
            {
                "period_start": "2026-08-01",
                "currency": "SGD",
                "categories": {"food": 120},
                "coverage": "unconfirmed",
            }
        ]
        assert context["profile_income"]["income_basis"] == "unconfirmed"


def test_direct_api_contract_rejects_unaffordable_planned_budget():
    with pytest.raises(ValidationError, match="exceed confirmed"):
        BudgetUpsert.model_validate(planning_draft())


def test_http_planning_clarification_shortfall_revision_confirmation_and_budget_readback(
    monkeypatch,
):
    from copy import deepcopy

    from fastapi.testclient import TestClient

    from app.api.routes import get_ai_service_client
    from app.core.config import settings
    from app.main import app

    calls = []

    class PlannerAI:
        async def coach(self, request):
            calls.append(request)
            if request.pending_budget:
                draft = deepcopy(request.pending_budget)
                if request.message == "all expenses included":
                    draft["planning"]["expenses_confirmed"] = True
                elif request.message == "Set hobbies to SGD 500":
                    draft["categories"][1]["limit_amount"] = 500
            else:
                draft = planning_draft()
                draft["planning"]["expenses_confirmed"] = False
            return CoachResponse(
                session_id=request.session_id,
                selected_agents=["budget"],
                answer="Unsaved plan",
                agent_results=[
                    {"agent": "budget", "summary": "Unsaved plan", "data": {"budget_draft": draft}}
                ],
                disclaimers=[],
                audit={},
            )

    app.dependency_overrides[get_ai_service_client] = PlannerAI
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    try:
        assert (
            client.put(
                "/api/users/u1/profile", headers=headers, json={"monthly_income": {"amount": 4000}}
            ).status_code
            == 200
        )

        def send(message):
            response = client.post(
                "/api/coach",
                headers=headers,
                json={"user_id": "u1", "session_id": "plan", "message": message},
            )
            assert response.status_code == 200, response.text
            return response.json()["answer"]

        assert "all your expenses" in send("Help create a realistic October 2026 budget")
        assert calls[0].budget_context["profile_income"]["income_basis"] == "unconfirmed"
        assert "Funding gap: SGD 200.00" in send("all expenses included")
        assert "Funding gap" in send("confirm budget")
        assert len(calls) == 2
        assert "confirm budget" in send("Set hobbies to SGD 500")
        assert send("confirm budget").startswith("Saved")
        assert len(calls) == 3
        response = client.get("/api/users/u1/budget?period_start=2026-10-01", headers=headers)
        assert response.status_code == 200
        assert response.json()["planning"]["savings_target"] == 800
        assert response.json()["total_limit"] == 3200
        # UI edits cannot exceed income while keeping the plan's savings allocation.
        invalid = client.put(
            "/api/users/u1/budget",
            headers=headers,
            json={
                "period_start": "2026-10-01",
                "currency": "SGD",
                "planning": response.json()["planning"],
                "categories": [{"category": "housing", "limit_amount": 4000}],
            },
        )
        assert invalid.status_code == 422
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


def test_known_funding_gap_remains_visible_while_clarifying_other_questions(db_session_factory):
    with db_session_factory() as session:
        draft = planning_draft(questions=["Would you like to choose a budgeting method?"])
        response = stage(session, draft)
        assert "Funding gap: SGD 200.00" in response.answer
        assert "choose a budgeting method" in response.answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None
