from copy import deepcopy
from datetime import date

from fastapi.testclient import TestClient
from test_budget_planning import confirm, stage

from app.api.financial_schemas import BudgetUpsert, ProfileUpsert, TransactionCreate
from app.core.config import settings
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
    SQLAlchemyUserRepository,
)
from app.main import app
from app.services.budget_review import build_budget_review

MONTH = date(2026, 9, 1)
TODAY = date(2026, 9, 15)


def setup_plan(session, categories=None):
    SQLAlchemyUserRepository(session).upsert_profile(
        "u1", ProfileUpsert(monthly_income={"amount": 2000})
    )
    payload = {
        "period_start": MONTH,
        "currency": "SGD",
        "planning": {
            "take_home_income": 2000,
            "savings_target": 500,
            "income_basis": "take_home",
            "expenses_confirmed": True,
        },
        "categories": categories
        or [
            {"category": "food", "limit_amount": 100},
            {"category": "housing", "limit_amount": 1000},
        ],
    }
    SQLAlchemyBudgetRepository(session).upsert("u1", BudgetUpsert.model_validate(payload))
    return payload


def transaction(
    session, category, amount, day=5, recurring=False, user="u1", currency="SGD", month="2026-09"
):
    SQLAlchemyTransactionRepository(session).create(
        user,
        TransactionCreate(
            description="Private receipt",
            category=category,
            occurred_on=f"{month}-{day:02d}",
            recurring=recurring,
            amount={"amount": amount, "currency": currency},
        ),
    )


def test_review_scopes_owner_currency_dates_and_excludes_transfers(db_session_factory):
    with db_session_factory() as session:
        setup_plan(session)
        transaction(session, "food", 50)
        transaction(session, "food", 700, day=20)
        transaction(session, "food", 600, month="2026-08")
        transaction(session, "food", 500, currency="USD")
        transaction(session, "food", 400, user="u2")
        transaction(session, "savings", 300)
        transaction(session, "pets", 25)
        review = build_budget_review(session, "u1", MONTH, today=TODAY)
        assert review["total_spent"] == 75
        assert review["unbudgeted_spent"] == 25
        assert review["excluded_transfers"] == 300
        assert review["as_of"] == "2026-09-15"
        assert "Private receipt" not in str(review)
        assert not review["saved"]


def test_pace_holds_recurring_amount_constant_and_never_counts_missing_as_zero(db_session_factory):
    with db_session_factory() as session:
        setup_plan(session)
        transaction(session, "food", 30, recurring=True)
        for day in (2, 5, 8):
            transaction(session, "food", 50, day=day)
        transaction(session, "housing", 1000, recurring=True)
        review = build_budget_review(session, "u1", MONTH, today=TODAY)
        rows = {row["category"]: row for row in review["categories"]}
        assert rows["food"]["pace_estimate"] == 330
        assert rows["food"]["pace_over_limit"] == 230
        assert rows["housing"]["pace_estimate"] is None
        assert review["total_pace_estimate"] is None
        assert review["suggestions"] == [] and review["comparison"] is None
        assert rows["food"]["remaining_per_day"] == 0
        assert review["remaining_days"] == 15


def test_early_and_sparse_data_have_no_pace_estimate(db_session_factory):
    with db_session_factory() as session:
        setup_plan(session, [{"category": "food", "limit_amount": 100}])
        for day in (1, 2, 3):
            transaction(session, "food", 10, day=day)
        early = build_budget_review(session, "u1", MONTH, today=date(2026, 9, 4))
        assert early["total_pace_estimate"] is None
        mature = build_budget_review(session, "u1", MONTH, today=TODAY)
        assert mature["total_pace_estimate"] == 60
        assert mature["categories"][0]["remaining_per_day"] == 4.67


def test_future_closed_leap_month_and_zero_limit(db_session_factory):
    with db_session_factory() as session:
        setup_plan(session, [{"category": "food", "limit_amount": 0}])
        transaction(session, "food", 10)
        future = build_budget_review(session, "u1", MONTH, today=date(2026, 8, 31))
        assert future["total_spent"] == 0 and future["elapsed_days"] == 0
        assert future["comparison"] is None
        closed = build_budget_review(session, "u1", MONTH, today=date(2026, 10, 1))
        assert closed["as_of"] == "2026-09-30"
        assert closed["categories"][0]["status"] == "over"
        assert closed["total_pace_estimate"] is None
        leap = build_budget_review(session, "u1", date(2024, 2, 1), today=TODAY)
        assert leap["elapsed_days"] == 29


def test_review_reports_overages_without_choosing_or_saving_new_limits(db_session_factory):
    with db_session_factory() as session:
        setup_plan(session)
        transaction(session, "food", 700)
        transaction(session, "pets", 25)
        review = build_budget_review(session, "u1", MONTH, today=TODAY)
        assert review["version"] == "budget-review-v2"
        assert review["suggestions"] == []
        assert review["comparison"] is None
        assert review["total_spent"] == 725
        assert review["unbudgeted_spent"] == 25
        assert {row["category"]: row["status"] for row in review["categories"]}["food"] == "over"
        record = SQLAlchemyBudgetRepository(session).get("u1", MONTH)
        assert record.planning["savings_target"] == 500
        assert {row.category: float(row.limit_amount) for row in record.categories} == {
            "food": 100, "housing": 1000,
        }


def stage_chosen_change(session, *, legacy_review=False):
    """Explicit alternative, optionally carrying evidence from a persisted v1 review."""
    record = SQLAlchemyBudgetRepository(session).get("u1", MONTH)
    payload = {
        "period_start": MONTH.isoformat(),
        "currency": "SGD",
        "categories": [
            {"category": row.category, "limit_amount": float(row.limit_amount)}
            for row in record.categories
        ],
        "planning": {key: value for key, value in record.planning.items() if key != "version"},
        "action": "compare",
        "scenarios": [{
            "name": "My food change",
            "categories": [{"category": "food", "limit_amount": 150}],
        }],
    }
    stage(session, payload)
    if legacy_review:
        chat = SQLAlchemyChatRepository(session).get("u1", "plan")
        chat.pending_budget = {
            **chat.pending_budget,
            "review_evidence": build_budget_review(session, "u1", MONTH, today=TODAY)["evidence_fingerprint"],
        }
        session.commit()


def test_review_requires_date_and_does_not_replace_existing_draft(db_session_factory):
    with db_session_factory() as session:
        assert "month and year" in stage(session, {"action": "review"}).answer
        assert "review cannot be saved" in confirm(session).answer
        confirm(session, "cancel")
        setup_plan(session)
        stage(
            session,
            {
                "period_start": "2026-10-01",
                "currency": "SGD",
                "categories": [{"category": "food", "limit_amount": 123}],
            },
        )
        chat = SQLAlchemyChatRepository(session).get("u1", "plan")
        previous = deepcopy(chat.pending_budget["draft"])
        response = stage(session, {"action": "review", "period_start": MONTH.isoformat()})
        assert "existing draft was kept" in response.answer
        assert chat.pending_budget["draft"] == previous
        assert chat.pending_budget["ready"] is False


def test_coach_adjustment_requires_adoption_and_reconfirmation(db_session_factory, monkeypatch):
    from app.services import budget_capture

    monkeypatch.setattr(
        budget_capture,
        "build_budget_review",
        lambda session, user, period: build_budget_review(session, user, period, today=TODAY),
    )
    with db_session_factory() as session:
        setup_plan(session)
        transaction(session, "food", 150)
        review = stage(session, {"action": "review", "period_start": MONTH.isoformat()})
        assert "Cover recorded spending" not in review.answer
        chat = SQLAlchemyChatRepository(session).get("u1", "plan")
        assert "comparison" not in chat.pending_budget
        assert "review_evidence" not in chat.pending_budget
        assert "cannot be saved" in confirm(session).answer
        stage_chosen_change(session)
        assert "unsaved draft" in confirm(session, "use scenario My food change").answer
        chat = SQLAlchemyChatRepository(session).get("u1", "plan")
        draft = deepcopy(chat.pending_budget["draft"])
        assert draft["planning"]["income_basis"] == "unknown"
        assert draft["planning"]["expenses_confirmed"] is False
        draft["planning"].update(income_basis="take_home", expenses_confirmed=True)
        stage(session, draft)
        assert confirm(session).answer.startswith("Saved")
        record = SQLAlchemyBudgetRepository(session).get("u1", MONTH)
        assert {row.category: float(row.limit_amount) for row in record.categories}["food"] == 150


def test_new_records_invalidate_coach_review_adoption(db_session_factory, monkeypatch):
    from app.services import budget_capture

    monkeypatch.setattr(
        budget_capture,
        "build_budget_review",
        lambda session, user, period: build_budget_review(session, user, period, today=TODAY),
    )
    with db_session_factory() as session:
        setup_plan(session)
        transaction(session, "food", 150)
        stage_chosen_change(session, legacy_review=True)
        transaction(session, "food", 20)
        assert (
            "fresh budget review" in confirm(session, "use scenario My food change").answer
        )


def test_api_review_is_read_only_and_stale_evidence_blocks_save(db_session_factory, monkeypatch):
    from app.api import financial

    monkeypatch.setattr(
        financial,
        "build_budget_review",
        lambda session, user, period: build_budget_review(session, user, period, today=TODAY),
    )
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    with db_session_factory() as session:
        payload = setup_plan(session)
        transaction(session, "food", 150)
        session.commit()
    response = client.get("/api/users/u1/budget/review?period_start=2026-09-01", headers=headers)
    assert response.status_code == 200
    assert response.json()["total_spent"] == 150
    assert response.json()["comparison"] is None
    assert response.json()["suggestions"] == []
    payload["period_start"] = MONTH.isoformat()
    payload["review_evidence"] = response.json()["evidence_fingerprint"]
    with db_session_factory() as session:
        transaction(session, "food", 10)
        session.commit()
    assert client.put("/api/users/u1/budget", headers=headers, json=payload).status_code == 409
    assert (
        client.get(
            "/api/users/u1/budget/review?period_start=2026-09-02", headers=headers
        ).status_code
        == 422
    )
    assert client.get("/api/users/u1/budget/review?period_start=2026-09-01").status_code in (
        401,
        403,
    )


def test_review_evidence_is_kept_until_final_confirmation(db_session_factory, monkeypatch):
    from app.services import budget_capture

    monkeypatch.setattr(
        budget_capture,
        "build_budget_review",
        lambda session, user, period: build_budget_review(session, user, period, today=TODAY),
    )
    with db_session_factory() as session:
        setup_plan(session)
        transaction(session, "food", 150)
        stage_chosen_change(session, legacy_review=True)
        confirm(session, "use scenario My food change")
        chat = SQLAlchemyChatRepository(session).get("u1", "plan")
        draft = deepcopy(chat.pending_budget["draft"])
        draft["planning"].update(income_basis="take_home", expenses_confirmed=True)
        stage(session, draft)
        assert chat.pending_budget["review_origin"]
        transaction(session, "food", 10)
        assert "out of date" in confirm(session).answer
        assert "out of date" in stage(session, draft).answer
        record = SQLAlchemyBudgetRepository(session).get("u1", MONTH)
        assert {row.category: float(row.limit_amount) for row in record.categories}["food"] == 100


def test_review_endpoint_enforces_profile_ownership(monkeypatch):
    from test_security import StubTokenVerifier

    from app.core import security

    monkeypatch.setattr(settings, "oidc_auth_enabled", True)
    monkeypatch.setattr(security, "get_oidc_token_verifier", StubTokenVerifier)
    client = TestClient(app)
    alice = {"Authorization": "Bearer alice-token"}
    bob = {"Authorization": "Bearer bob-token"}
    assert (
        client.post("/api/profiles", headers=alice, json={"user_id": "alice-review"}).status_code
        == 201
    )
    assert (
        client.get(
            "/api/users/alice-review/budget/review?period_start=2026-09-01", headers=bob
        ).status_code
        == 404
    )
    review = client.get(
        "/api/users/alice-review/budget/review?period_start=2026-09-01", headers=alice
    )
    assert review.status_code == 200
    assert review.json()["has_budget"] is False


def test_non_sgd_budget_is_not_converted_or_adjusted(db_session_factory):
    with db_session_factory() as session:
        SQLAlchemyBudgetRepository(session).upsert(
            "u1",
            BudgetUpsert.model_validate(
                {
                    "period_start": MONTH,
                    "currency": "USD",
                    "categories": [{"category": "food", "limit_amount": 100}],
                }
            ),
        )
        transaction(session, "food", 150)
        review = build_budget_review(session, "u1", MONTH, today=TODAY)
        assert review["supported"] is False
        assert review["total_limit"] is None
        assert review["suggestions"] == []
        assert review["comparison"] is None
