from datetime import date

import pytest
from pydantic import ValidationError

from app.api.financial_schemas import BudgetCategoryInput, BudgetUpsert
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import SQLAlchemyBudgetRepository, SQLAlchemyChatRepository
from app.services.budget_capture import handle_budget_confirmation, stage_budget_draft

PERIOD = date(2026, 10, 1)


def response(draft, *, blocked=False):
    return CoachResponse(
        session_id="budget-chat",
        selected_agents=["budget"],
        answer="draft",
        blocked=blocked,
        disclaimers=[],
        audit={},
        agent_results=[{"agent": "budget", "summary": "Draft", "data": {"budget_draft": draft}}],
    )


def complete_draft(**updates):
    return {
        "period_start": "2026-10-01",
        "currency": "SGD",
        "categories": [
            {"category": "Food", "limit_amount": 500},
            {"category": "Pet care", "limit_amount": 120},
        ],
        **updates,
    }


def setup_draft(session, draft=None):
    chat = SQLAlchemyChatRepository(session).create("u1", "budget-chat", "Budget")
    reply = response(draft if draft is not None else complete_draft())
    stage_budget_draft(session, "u1", chat, reply)
    session.commit()
    return reply


def confirm(session, message="confirm budget", session_id="budget-chat", user_id="u1"):
    return handle_budget_confirmation(
        session,
        CoachRequest(
            user_id=user_id,
            session_id=session_id,
            message=message,
        ),
    )


def test_draft_survives_sessions_and_only_confirmation_writes(db_session_factory):
    with db_session_factory() as session:
        reply = setup_draft(session)
        assert "Nothing has been saved" in reply.answer
        assert "pet care" in reply.answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None
    with db_session_factory() as session:
        assert confirm(session).answer.startswith("Saved")
        session.commit()
        record = SQLAlchemyBudgetRepository(session).get("u1", PERIOD)
        assert {row.category: float(row.limit_amount) for row in record.categories} == {
            "food": 500,
            "pet care": 120,
        }
        assert "no pending budget" in confirm(session).answer


@pytest.mark.parametrize(
    "draft,question",
    [
        (complete_draft(period_start=None), "month and year"),
        (complete_draft(currency=None), "SGD"),
        (complete_draft(currency="USD"), "SGD"),
        (complete_draft(categories=[]), "categories and monthly limits"),
        (complete_draft(categories=[{"category": None, "limit_amount": 100}]), "category for"),
        (
            complete_draft(categories=[{"category": "food", "limit_amount": None}]),
            "monthly limit for food",
        ),
        (complete_draft(questions=["Is that a weekly or monthly limit?"]), "weekly or monthly"),
        (
            complete_draft(
                categories=[
                    {"category": "food", "limit_amount": 1},
                    {"category": " FOOD ", "limit_amount": 2},
                ]
            ),
            "duplicate",
        ),
    ],
)
def test_missing_or_ambiguous_details_cannot_be_confirmed(db_session_factory, draft, question):
    with db_session_factory() as session:
        reply = setup_draft(session, draft)
        assert question in reply.answer
        assert question in confirm(session, "yes").answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None


def test_cancel_and_conversation_isolation(db_session_factory):
    with db_session_factory() as session:
        setup_draft(session)
        assert "no pending" in confirm(session, session_id="another-chat").answer
        assert "no pending" in confirm(session, user_id="another-user").answer
        assert "cancelled" in confirm(session, "cancel").answer
        assert "no pending" in confirm(session).answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None


def test_preserve_other_categories_and_reconfirm_after_budget_page_edit(db_session_factory):
    with db_session_factory() as session:
        repo = SQLAlchemyBudgetRepository(session)
        repo.upsert(
            "u1",
            BudgetUpsert(
                period_start=PERIOD,
                categories=[
                    BudgetCategoryInput(category="housing", limit_amount=1000),
                    BudgetCategoryInput(category="food", limit_amount=200),
                ],
            ),
        )
        setup_draft(session)
        repo.upsert(
            "u1",
            BudgetUpsert(
                period_start=PERIOD,
                categories=[
                    BudgetCategoryInput(category="housing", limit_amount=1100),
                    BudgetCategoryInput(category="food", limit_amount=300),
                ],
            ),
        )
        session.commit()
        answer = confirm(session).answer
        assert "fresh preview" in answer
        assert "was SGD 300.00" in answer
        assert confirm(session).answer.startswith("Saved")
        session.commit()
        assert {
            row.category: float(row.limit_amount) for row in repo.get("u1", PERIOD).categories
        } == {
            "housing": 1100,
            "food": 500,
            "pet care": 120,
        }


def test_correction_requires_new_preview_and_blocked_output_disarms_old_preview(db_session_factory):
    with db_session_factory() as session:
        setup_draft(session)
        chat = SQLAlchemyChatRepository(session).get("u1", "budget-chat")
        stage_budget_draft(
            session,
            "u1",
            chat,
            response(
                complete_draft(
                    categories=[
                        {"category": "food", "limit_amount": 0},
                    ]
                )
            ),
        )
        assert confirm(session, "yes but make it 200") is None
        stage_budget_draft(session, "u1", chat, response(complete_draft(), blocked=True))
        assert "fresh preview" in confirm(session).answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None
        assert confirm(session).answer.startswith("Saved")
        session.commit()
        assert (
            float(SQLAlchemyBudgetRepository(session).get("u1", PERIOD).categories[0].limit_amount)
            == 0
        )


@pytest.mark.parametrize(
    "category,amount",
    [("   ", 1), ("food", float("inf")), ("food", -1), ("food", 1.234), ("food", 1e12)],
)
def test_budget_validation_rejects_blank_categories_and_invalid_limits(category, amount):
    with pytest.raises(ValidationError):
        BudgetCategoryInput(category=category, limit_amount=amount)


def test_coach_http_flow_clarifies_then_confirms_without_ai_writes():
    from fastapi.testclient import TestClient

    from app.api.routes import get_ai_service_client
    from app.core.config import settings
    from app.main import app

    calls = []

    class BudgetAI:
        async def coach(self, request):
            calls.append(request)
            draft = complete_draft(period_start=None) if len(calls) == 1 else complete_draft()
            reply = response(draft)
            reply.session_id = request.session_id
            return reply

    app.dependency_overrides[get_ai_service_client] = BudgetAI
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    try:
        client.put("/api/users/u1/profile", headers=headers, json={})

        def send(message):
            result = client.post(
                "/api/coach",
                headers=headers,
                json={
                    "user_id": "u1",
                    "session_id": "budget-chat",
                    "message": message,
                },
            )
            assert result.status_code == 200, result.text
            return result.json()

        assert (
            "month and year" in send("Set budgets for food SGD 500 and pet care SGD 120")["answer"]
        )
        assert "Nothing has been saved" in send("October 2026")["answer"]
        assert calls[-1].pending_budget["categories"][1]["category"] == "Pet care"
        assert (
            client.get("/api/users/u1/budget?period_start=2026-10-01", headers=headers).status_code
            == 404
        )
        assert send("confirm budget")["answer"].startswith("Saved")
        assert len(calls) == 2
        budget = client.get("/api/users/u1/budget?period_start=2026-10-01", headers=headers)
        assert budget.status_code == 200
        assert budget.json()["total_limit"] == 620
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


def test_expired_preview_needs_confirmation_again(db_session_factory):
    with db_session_factory() as session:
        setup_draft(session)
        chat = SQLAlchemyChatRepository(session).get("u1", "budget-chat")
        chat.pending_budget = {**chat.pending_budget, "expires_at": "2000-01-01T00:00:00+00:00"}
        assert "fresh preview" in confirm(session).answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None


def test_confirmation_rollback_keeps_draft_for_retry(db_session_factory):
    with db_session_factory() as session:
        setup_draft(session)
        assert confirm(session).answer.startswith("Saved")
        # A failed chat commit must roll back both the budget and draft consumption.
        session.rollback()
    with db_session_factory() as session:
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None
        assert confirm(session).answer.startswith("Saved")
        session.commit()
