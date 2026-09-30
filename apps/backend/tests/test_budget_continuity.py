from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.financial_schemas import BudgetUpsert, TransactionCreate
from app.core.config import settings
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyTransactionRepository,
)
from app.main import app
from app.services.budget_continuity import (
    BatchConfirmation,
    ContinuityRequest,
    ReviewAcknowledgement,
    ReviewPreferences,
    acknowledge_review,
    confirm_batch,
    preview_batch,
    review_due,
)
from app.services.financial_workspace import read_section, write_section

TODAY = date(2026, 10, 10)
SOURCE = date(2026, 9, 1)
FIRST = date(2026, 10, 1)


def setup(session):
    repo = SQLAlchemyBudgetRepository(session)
    repo.upsert(
        "u",
        BudgetUpsert(
            period_start=SOURCE,
            categories=[
                {"category": "food", "limit_amount": 500},
                {"category": "fun", "limit_amount": 100},
            ],
            planning={"take_home_income": 2000, "savings_target": 500},
        ),
    )
    for category, amount in [("food", 400), ("fun", 200)]:
        SQLAlchemyTransactionRepository(session).create(
            "u",
            TransactionCreate(
                description=category,
                category=category,
                amount={"amount": amount},
                occurred_on=date(2026, 9, 15),
            ),
        )
    return repo


def request(**overrides):
    return ContinuityRequest.model_validate(
        {
            "source_period": SOURCE,
            "first_period": FIRST,
            "months": 3,
            "take_home_income": 2000,
            "savings_target": 500,
            "carry_rule": "carry_net",
            **overrides,
        }
    )


def confirm(preview):
    return BatchConfirmation(preview_id=preview["preview_id"], confirmed=True)


def test_rollover_preview_does_not_save_and_applies_once(db_session_factory):
    with db_session_factory() as session:
        repo = setup(session)
        preview = preview_batch(session, "u", request(), today=TODAY)
        assert preview["ready"]
        assert repo.get("u", FIRST) is None
        assert preview["carry_amounts"] == {"food": 100, "fun": -100}
        assert preview["plans"][0]["budget"]["categories"] == [
            {"category": "food", "limit_amount": 600},
            {"category": "fun", "limit_amount": 0},
        ]
        assert preview["plans"][1]["budget"]["categories"] == [
            {"category": "food", "limit_amount": 500},
            {"category": "fun", "limit_amount": 100},
        ]
        result = confirm_batch(session, "u", confirm(preview), today=TODAY)
        assert len(result["periods"]) == 3
        assert repo.get("u", date(2026, 12, 1)).planning["savings_target"] == 500
        with pytest.raises(ValueError, match="consumed"):
            confirm_batch(session, "u", confirm(preview), today=TODAY)


def test_changed_spending_expires_preview_without_partial_writes(db_session_factory):
    with db_session_factory() as session:
        repo = setup(session)
        preview = preview_batch(session, "u", request(), today=TODAY)
        SQLAlchemyTransactionRepository(session).create(
            "u",
            TransactionCreate(
                description="late",
                category="food",
                amount={"amount": 10},
                occurred_on=date(2026, 9, 16),
            ),
        )
        with pytest.raises(ValueError, match="changed"):
            confirm_batch(session, "u", confirm(preview), today=TODAY)
        assert repo.get("u", FIRST) is None
        assert repo.get("u", date(2026, 11, 1)) is None


def test_insufficient_income_and_existing_targets_block_batch(db_session_factory):
    with db_session_factory() as session:
        repo = setup(session)
        preview = preview_batch(session, "u", request(take_home_income=600), today=TODAY)
        assert not preview["ready"] and preview["plans"][0]["funding_gap"] == 500
        with pytest.raises(ValueError, match="incomplete"):
            confirm_batch(session, "u", confirm(preview), today=TODAY)
        repo.upsert("u", BudgetUpsert(period_start=FIRST, categories=[]))
        blocked = preview_batch(session, "u", request(), today=TODAY)
        assert not blocked["ready"]
        approved = preview_batch(session, "u", request(allow_overwrite=True), today=TODAY)
        assert approved["ready"] and approved["plans"][0]["previous"] is not None


def test_open_month_cannot_roll_and_expired_or_foreign_preview_cannot_save(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        with pytest.raises(ValueError, match="completed"):
            preview_batch(session, "u", request(), today=date(2026, 9, 20))
        preview = preview_batch(session, "u", request(carry_rule="copy_limits"), today=TODAY)
        with pytest.raises(ValueError, match="not found"):
            confirm_batch(session, "other", confirm(preview), today=TODAY)
        preview["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        write_section(session, "u", "pending_batch", preview)
        with pytest.raises(ValueError, match="expired"):
            confirm_batch(session, "u", confirm(preview), today=TODAY)


def test_runtime_failure_rolls_back_whole_batch(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        repo = setup(session)
        preview = preview_batch(session, "u", request(), today=TODAY)
        original = SQLAlchemyBudgetRepository.upsert

        def failing(self, user, payload):
            if payload.period_start.month == 11:
                raise RuntimeError("simulated write failure")
            return original(self, user, payload)

        monkeypatch.setattr(SQLAlchemyBudgetRepository, "upsert", failing)
        with pytest.raises(RuntimeError):
            confirm_batch(session, "u", confirm(preview), today=TODAY)
        assert repo.get("u", FIRST) is None
        assert read_section(session, "u", "pending_batch")["preview_id"] == preview["preview_id"]


def test_reviews_opt_in_refresh_evidence_and_never_change_budgets(db_session_factory):
    with db_session_factory() as session:
        repo = setup(session)
        assert review_due(session, "u", today=TODAY) == {"enabled": False, "due": False}
        prefs = ReviewPreferences(
            enabled=True, cadence="monthly", next_review_on=TODAY, confirmed=True
        )
        write_section(session, "u", "review_preferences", prefs.model_dump(mode="json"))
        due = review_due(session, "u", today=TODAY, include_review=True)
        assert due["due"] and due["period_start"] == "2026-09-01"
        assert review_due(session, "other", today=TODAY)["due"] is False
        SQLAlchemyTransactionRepository(session).create(
            "u",
            TransactionCreate(
                description="late", category="food", amount={"amount": 1}, occurred_on=SOURCE
            ),
        )
        with pytest.raises(ValueError, match="changed"):
            acknowledge_review(
                session,
                "u",
                ReviewAcknowledgement(evidence=due["evidence"], confirmed=True),
                today=TODAY,
            )
        due = review_due(session, "u", today=TODAY, include_review=True)
        result = acknowledge_review(
            session,
            "u",
            ReviewAcknowledgement(evidence=due["evidence"], confirmed=True),
            today=TODAY,
        )
        assert not result["due"] and result["next_review_on"] == "2026-11-10"
        assert repo.get("u", FIRST) is None
        prefs.enabled = False
        write_section(session, "u", "review_preferences", prefs.model_dump(mode="json"))
        assert not review_due(session, "u", today=date(2027, 1, 1))["due"]


def test_api_requires_confirmation_and_has_owned_preview(db_session_factory, monkeypatch):
    from app.services import budget_continuity

    monkeypatch.setattr(budget_continuity, "local_today", lambda: TODAY)
    with db_session_factory() as session:
        setup(session)
        session.commit()
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    path = "/api/users/u/budget/continuity/preview"
    assert client.post(path, json=request().model_dump(mode="json")).status_code in (401, 403)
    response = client.post(path, headers=headers, json=request().model_dump(mode="json"))
    assert response.status_code == 200
    preview_id = response.json()["preview_id"]
    assert (
        client.post(
            "/api/users/u/budget/continuity/confirm",
            headers=headers,
            json={"preview_id": preview_id},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/users/other/budget/continuity/confirm",
            headers=headers,
            json={"preview_id": preview_id, "confirmed": True},
        ).status_code
        == 409
    )
    assert client.post(
        "/api/users/u/budget/continuity/confirm",
        headers=headers,
        json={"preview_id": preview_id, "confirmed": True},
    ).json()["saved"]


def test_coach_continuity_missing_details_remain_an_unsaved_draft(db_session_factory):
    from app.domain.schemas import CoachResponse
    from app.infrastructure.repositories import SQLAlchemyChatRepository
    from app.services.budget_capture import stage_budget_draft
    with db_session_factory() as session:
        repo = setup(session)
        chat = SQLAlchemyChatRepository(session).create("u", "s", "Plan")
        response = CoachResponse(session_id="s", selected_agents=["budget"], answer="draft", agent_results=[{"agent": "budget", "summary": "draft", "data": {"budget_draft": {"action": "continuity"}}}], disclaimers=[], audit={})
        stage_budget_draft(session, "u", chat, response)
        assert "Plan upcoming months" in response.answer
        assert repo.get("u", FIRST) is None
        assert not chat.pending_budget["ready"]


def test_gross_alternative_income_is_not_assumed_take_home(db_session_factory):
    from app.domain.schemas import CoachResponse
    from app.infrastructure.repositories import SQLAlchemyChatRepository
    from app.services.budget_capture import stage_budget_draft
    with db_session_factory() as session:
        setup(session)
        chat = SQLAlchemyChatRepository(session).create("u", "s", "Plan")
        response = CoachResponse(session_id="s", selected_agents=["budget"], answer="draft", agent_results=[{"agent": "budget", "summary": "draft", "data": {"budget_draft": {"action": "alternatives", "period_start": SOURCE.isoformat(), "planning": {"take_home_income": 4000, "income_basis": "gross"}}}}], disclaimers=[], audit={})
        stage_budget_draft(session, "u", chat, response)
        assert "confirm the alternative income is take-home" in response.answer
        assert chat.pending_budget is None
