import json
from datetime import UTC, date, datetime, timedelta

import pytest
from coach_i18n import translate
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.financial_schemas import BudgetUpsert, GoalCreate, TransactionCreate
from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.models import FinancialGoalRecord, MonthlyBudgetRecord, TransactionRecord
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyChatRepository,
    SQLAlchemyGoalRepository,
    SQLAlchemyTransactionRepository,
)
from app.main import app
from app.services.budget_capacity import build_capacity_context
from app.services.budget_capture import handle_budget_confirmation, stage_budget_draft
from app.services.budget_constraints import AllocationPolicy, save_policy
from app.services.budget_history import RestoreRequest, history, restore_payload
from app.services.budget_records import build_record_change
from app.services.budget_workspace import WorkspaceChange, confirm_change, preview_change

OCT, NOV, DEC = (date(2026, month, 1) for month in (10, 11, 12))
SCOPE = {"kind": "range", "start": str(OCT), "end": str(DEC)}
HEADERS = {"X-API-Key": settings.api_key}


def save(session, period=OCT, user="budget-u", income=4000, savings=700):
    return SQLAlchemyBudgetRepository(session).upsert(
        user,
        BudgetUpsert(
            period_start=period,
            categories=[
                {"category": "food", "limit_amount": 500},
                {"category": "transport", "limit_amount": 200},
            ],
            planning={"take_home_income": income, "savings_target": savings},
        ),
    )


def command(action="edit", scope=None, **values):
    return WorkspaceChange(
        operation="budgets",
        payload_json=json.dumps({"action": action, "scope": scope or SCOPE, **values}),
    )


def response(change, scope=None):
    return CoachResponse(
        session_id="budget-chat",
        selected_agents=["budget"],
        answer="Draft",
        disclaimers=[],
        agent_results=[
            {
                "agent": "budget",
                "summary": "Draft",
                "data": {
                    "budget_draft": {
                        "action": "workspace",
                        "workspace": change.model_dump(mode="json"),
                    }
                },
            }
        ],
        audit={"turn_decision": {"budget_scope": scope}} if scope else {},
    )


def confirm(session, message="confirm budget"):
    return handle_budget_confirmation(
        session, CoachRequest(user_id="budget-u", session_id="budget-chat", message=message)
    )


def test_year_read_includes_saved_months_and_missing_months_without_writes(db_session_factory):
    with db_session_factory() as session:
        save(session, OCT)
        save(session, DEC, savings=900)
        save(session, NOV, user="other-u")
        SQLAlchemyTransactionRepository(session).create(
            "budget-u",
            TransactionCreate(
                description="Lunch",
                amount={"amount": 20},
                occurred_on="2026-10-02",
                category="food",
            ),
        )
        _, result = build_record_change(
            session,
            "budget-u",
            {
                "action": "compare",
                "scope": {"kind": "range", "start": "2026-01-01", "end": "2026-12-01"},
            },
        )
        assert [r["period_start"] for r in result["rows"]] == [str(OCT), str(DEC)]
        assert str(NOV) in result["missing_periods"]
        assert result["totals"]["SGD"] == {
            "limits": 1400,
            "recorded_spending": 20,
            "savings": 1600,
            "planning_months": 2,
        }
        assert not session.new and not session.dirty and not session.deleted
        _, all_saved = build_record_change(
            session, "budget-u", {"action": "read", "scope": {"kind": "all"}}
        )
        assert len(all_saved["rows"]) == 2


def test_multi_month_edit_preserves_each_plan_and_requires_confirmation(db_session_factory):
    with db_session_factory() as session:
        for index, period in enumerate((OCT, NOV, DEC)):
            save(session, period, income=4000 + index * 500, savings=700 + index * 100)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        change = command(categories=[{"category": "food", "limit_amount": 600}])
        reply = response(change)
        stage_budget_draft(session, "budget-u", chat, reply)
        assert reply.audit["action_status"] == "preview"
        assert "2026-10" in reply.answer and "2026-12" in reply.answer
        assert (
            SQLAlchemyBudgetRepository(session).get("budget-u", OCT).categories[0].limit_amount
            == 500
        )
        assert confirm(session).audit["action_status"] == "saved"
        for index, period in enumerate((OCT, NOV, DEC)):
            record = SQLAlchemyBudgetRepository(session).get("budget-u", period)
            assert {r.category: float(r.limit_amount) for r in record.categories} == {
                "food": 600,
                "transport": 200,
            }
            assert record.planning["take_home_income"] == 4000 + index * 500
            assert record.planning["savings_target"] == 700 + index * 100
        assert confirm(session).audit["action_status"] == "no_pending"


def test_category_removal_keeps_transactions_and_other_limits(db_session_factory):
    with db_session_factory() as session:
        save(session)
        transaction = SQLAlchemyTransactionRepository(session).create(
            "budget-u",
            TransactionCreate(
                description="Lunch",
                amount={"amount": 20},
                occurred_on="2026-10-02",
                category="food",
            ),
        )
        preview = preview_change(
            session,
            "budget-u",
            command(scope={"kind": "periods", "periods": [str(OCT)]}, remove_categories=[" FOOD "]),
        )
        confirm_change(session, "budget-u", preview)
        record = SQLAlchemyBudgetRepository(session).get("budget-u", OCT)
        assert [r.category for r in record.categories] == ["transport"]
        assert session.get(TransactionRecord, transaction.id) is not None


def test_planning_patch_preserves_each_month_and_requires_take_home_basis(db_session_factory):
    with db_session_factory() as session:
        save(session, OCT, income=4000)
        save(session, NOV, income=5000)
        scope = {"kind": "range", "start": str(OCT), "end": str(NOV)}
        preview = preview_change(
            session, "budget-u", command(scope=scope, planning={"savings_target": 900})
        )
        confirm_change(session, "budget-u", preview)
        for period, income in ((OCT, 4000), (NOV, 5000)):
            plan = SQLAlchemyBudgetRepository(session).get("budget-u", period).planning
            assert plan["take_home_income"] == income and plan["savings_target"] == 900
        with pytest.raises(ValueError, match="take-home"):
            preview_change(
                session, "budget-u", command(scope=scope, planning={"take_home_income": 6000})
            )


def test_read_preview_cannot_be_confirmed_through_workspace_api(db_session_factory):
    with db_session_factory() as session:
        save(session)
        preview = preview_change(session, "budget-u", command("read", {"kind": "all"}))
        with pytest.raises(ValueError, match="read-only"):
            confirm_change(session, "budget-u", preview)


@pytest.mark.parametrize("other_saved_month", [False, True])
def test_set_missing_month_enters_funded_creation_without_borrowing_another_plan(db_session_factory, other_saved_month):
    with db_session_factory() as session:
        if other_saved_month:
            save(session, NOV, income=9000, savings=4000)
        save(session, DEC, user="other-u", income=8000, savings=3000)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        reply = CoachResponse(session_id="budget-chat", selected_agents=["budget"], answer="Draft", audit={},
                              disclaimers=[], agent_results=[{"agent": "budget", "summary": "Draft", "data": {
                                  "budget_draft": {"action": "set", "period_start": str(DEC),
                                                   "categories": [{"category": "food", "limit_amount": 650},
                                                                  {"category": "housing", "limit_amount": 1500}]}}}])
        stage_budget_draft(session, "budget-u", chat, reply, default_period=OCT)
        assert reply.audit["budget_capture"] == "needs_input"
        assert "take-home" in reply.answer and "savings" in reply.answer
        assert chat.pending_budget["draft"]["period_start"] == str(DEC)
        planning = chat.pending_budget["draft"]["planning"]
        assert planning["take_home_income"] is None and planning["savings_target"] is None
        assert SQLAlchemyBudgetRepository(session).get("budget-u", DEC) is None
        assert not chat.pending_budget["ready"]


def test_set_existing_month_previews_a_patch_and_preserves_funding_and_other_limits(db_session_factory):
    with db_session_factory() as session:
        save(session, DEC, income=5000, savings=1000)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        reply = CoachResponse(session_id="budget-chat", selected_agents=["budget"], answer="Draft", audit={},
                              disclaimers=[], agent_results=[{"agent": "budget", "summary": "Draft", "data": {
                                  "budget_draft": {"action": "set", "period_start": str(DEC),
                                                   "categories": [{"category": "food", "limit_amount": 650}]}}}])
        stage_budget_draft(session, "budget-u", chat, reply, default_period=OCT)
        assert reply.audit["action_status"] == "preview"
        before = SQLAlchemyBudgetRepository(session).get("budget-u", DEC)
        assert {row.category: float(row.limit_amount) for row in before.categories}["food"] == 500
        assert confirm(session).audit["action_status"] == "saved"
        after = SQLAlchemyBudgetRepository(session).get("budget-u", DEC)
        assert {row.category: float(row.limit_amount) for row in after.categories} == {"food": 650, "transport": 200}
        assert after.planning["take_home_income"] == 5000 and after.planning["savings_target"] == 1000


def test_explicit_edit_of_a_missing_month_still_cannot_create_a_plan(db_session_factory):
    with db_session_factory() as session:
        save(session, NOV)
        with pytest.raises(ValueError, match="saved"):
            preview_change(session, "budget-u", command("edit", {"kind": "periods", "periods": [str(DEC)]},
                           categories=[{"category": "food", "limit_amount": 650}]))
        assert SQLAlchemyBudgetRepository(session).get("budget-u", DEC) is None


@pytest.mark.parametrize("action", ["read", "delete"])
def test_new_record_action_does_not_inherit_previous_edit_fields(db_session_factory, action):
    with db_session_factory() as session:
        save(session)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        scope = {"kind": "periods", "periods": [str(OCT)]}
        stage_budget_draft(
            session,
            "budget-u",
            chat,
            response(
                command("edit", scope, categories=[{"category": "food", "limit_amount": 600}])
            ),
        )
        reply = response(command(action, scope))
        stage_budget_draft(session, "budget-u", chat, reply)
        assert reply.audit["action_status"] == ("read_only" if action == "read" else "preview")
        assert not chat.pending_budget["workspace_preview"]["target"]["categories"]
        if action == "delete":
            assert confirm(session).audit["action_status"] == "saved"
            assert SQLAlchemyBudgetRepository(session).get("budget-u", OCT) is None
        else:
            assert {
                r.category: float(r.limit_amount)
                for r in SQLAlchemyBudgetRepository(session).get("budget-u", OCT).categories
            }["food"] == 500


def test_delete_keeps_other_records_and_history_and_removes_capacity(db_session_factory):
    with db_session_factory() as session:
        save(session)
        save(session, NOV)
        goal = SQLAlchemyGoalRepository(session).create(
            "budget-u",
            GoalCreate(
                name="Course",
                target_amount={"amount": 1000},
                current_amount={"amount": 0},
                target_months=12,
            ),
        )
        preview = preview_change(
            session, "budget-u", command("delete", {"kind": "periods", "periods": [str(OCT)]})
        )
        confirm_change(session, "budget-u", preview)
        assert SQLAlchemyBudgetRepository(session).get("budget-u", OCT) is None
        assert SQLAlchemyBudgetRepository(session).get("budget-u", NOV) is not None
        assert session.get(FinancialGoalRecord, goal.id) is not None
        assert build_capacity_context(session, "budget-u", OCT)["source"] == "unavailable"
        entries = history(session, "budget-u", OCT)
        assert entries[-1]["reason"] == "Plan retained before confirmed deletion"
        payload = restore_payload(
            session, "budget-u", RestoreRequest(period_start=OCT, version_id=entries[-1]["id"])
        )
        assert payload.planning.savings_target == 700
        assert entries[0]["reason"] == "Confirmed save"


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_missing_month_rejects_entire_batch(db_session_factory, action):
    with db_session_factory() as session:
        save(session)
        kwargs = (
            {"categories": [{"category": "food", "limit_amount": 600}]} if action == "edit" else {}
        )
        with pytest.raises(ValueError, match="No saved budget for"):
            preview_change(session, "budget-u", command(action, **kwargs))
        assert (
            SQLAlchemyBudgetRepository(session).get("budget-u", OCT).planning["savings_target"]
            == 700
        )


@pytest.mark.parametrize("action", ["edit", "delete"])
def test_protected_category_blocks_removal_and_deletion(db_session_factory, action):
    with db_session_factory() as session:
        save(session)
        save_policy(
            session,
            "budget-u",
            AllocationPolicy(period_start=OCT, protected_categories=["food"], confirmed=True),
        )
        kwargs = {"remove_categories": ["food"]} if action == "edit" else {}
        with pytest.raises(ValueError, match="Keep food"):
            preview_change(
                session,
                "budget-u",
                command(action, {"kind": "periods", "periods": [str(OCT)]}, **kwargs),
            )


def test_empty_commitments_do_not_block_budget_deletion(db_session_factory):
    with db_session_factory() as session:
        save(session)
        save_policy(
            session,
            "budget-u",
            AllocationPolicy(period_start=OCT, minimum_savings=0, confirmed=True),
        )
        preview = preview_change(
            session, "budget-u", command("delete", {"kind": "periods", "periods": [str(OCT)]})
        )
        confirm_change(session, "budget-u", preview)
        assert SQLAlchemyBudgetRepository(session).get("budget-u", OCT) is None


def test_invalid_month_shortfall_blocks_all_changes(db_session_factory):
    with db_session_factory() as session:
        save(session, OCT)
        save(session, NOV, income=1500)
        change = command(
            scope={"kind": "range", "start": str(OCT), "end": str(NOV)},
            categories=[{"category": "food", "limit_amount": 800}],
        )
        with pytest.raises(ValueError, match="exceed"):
            preview_change(session, "budget-u", change)
        assert {
            r.category: float(r.limit_amount)
            for r in SQLAlchemyBudgetRepository(session).get("budget-u", OCT).categories
        }["food"] == 500


def test_batch_rollback_on_second_repository_failure(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        save(session, OCT)
        save(session, NOV)
        session.commit()
        preview = preview_change(
            session,
            "budget-u",
            command(
                scope={"kind": "range", "start": str(OCT), "end": str(NOV)},
                categories=[{"category": "food", "limit_amount": 600}],
            ),
        )
        original = SQLAlchemyBudgetRepository.upsert

        def failing(repository, user, payload):
            if payload.period_start == NOV:
                raise ValueError("Injected repository failure")
            return original(repository, user, payload)

        monkeypatch.setattr(SQLAlchemyBudgetRepository, "upsert", failing)
        with pytest.raises(ValueError, match="Injected"):
            confirm_change(session, "budget-u", preview)
        session.commit()
        for period in (OCT, NOV):
            assert {
                r.category: float(r.limit_amount)
                for r in SQLAlchemyBudgetRepository(session).get("budget-u", period).categories
            }["food"] == 500


@pytest.mark.parametrize("intervention", ["stale", "expired", "cancel", "read"])
def test_preview_cannot_apply_after_intervening_change(db_session_factory, intervention):
    with db_session_factory() as session:
        save(session)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        scope = {"kind": "periods", "periods": [str(OCT)]}
        stage_budget_draft(session, "budget-u", chat, response(command("delete", scope)))
        if intervention == "stale":
            save(session, savings=800)
        elif intervention == "expired":
            chat.pending_budget = {
                **chat.pending_budget,
                "workspace_preview": {
                    **chat.pending_budget["workspace_preview"],
                    "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                },
            }
        elif intervention == "cancel":
            assert confirm(session, "cancel").audit["action_status"] == "cancelled"
        else:
            stage_budget_draft(session, "budget-u", chat, response(command("read", scope)))
        assert confirm(session).audit["action_status"] != "saved"
        assert SQLAlchemyBudgetRepository(session).get("budget-u", OCT) is not None


def test_explicit_router_scope_wins_over_sidebar_default(db_session_factory):
    with db_session_factory() as session:
        save(session, OCT)
        save(session, NOV)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        reply = response(
            command("delete", {"kind": "default"}), {"kind": "periods", "periods": [str(NOV)]}
        )
        stage_budget_draft(session, "budget-u", chat, reply, default_period=OCT)
        assert chat.pending_budget["workspace_preview"]["target"]["scope"]["periods"] == [str(NOV)]
        confirm(session)
        assert SQLAlchemyBudgetRepository(session).get("budget-u", OCT) is not None
        assert SQLAlchemyBudgetRepository(session).get("budget-u", NOV) is None


def test_default_and_ambiguous_scopes(db_session_factory):
    with db_session_factory() as session:
        save(session)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        reply = response(command("read", {"kind": "default"}))
        stage_budget_draft(session, "budget-u", chat, reply, default_period=OCT)
        assert "2026-10" in reply.answer
        assert reply.audit["action_status"] == "read_only"
        unclear = response(command("delete", {"kind": "default"}))
        unclear.audit = {"turn_decision": {"budget_scope_unclear": True}}
        stage_budget_draft(session, "budget-u", chat, unclear, default_period=OCT)
        assert not chat.pending_budget["ready"]
        assert confirm(session).audit["action_status"] != "saved"


def test_chinese_records_preview_preserves_amounts_and_confirmation(db_session_factory):
    with db_session_factory() as session:
        save(session)
        chat = SQLAlchemyChatRepository(session).create("budget-u", "budget-chat", "Budget")
        reply = response(command("delete", {"kind": "periods", "periods": [str(OCT)]}))
        reply.audit["response_locale"] = "zh-Hans"
        stage_budget_draft(session, "budget-u", chat, reply)
        assert translate("budget_action.records_preview", "zh-Hans") in reply.answer
        assert "500.00" in reply.answer and "700.00" in reply.answer
        assert translate("budget_action.records_confirm", "zh-Hans") in reply.answer
        assert SQLAlchemyBudgetRepository(session).get("budget-u", OCT) is not None


def test_owned_listing_api_and_coach_confirmation(db_session_factory):
    with db_session_factory() as session:
        save(session)
        save(session, NOV)
        save(session, DEC, user="other-u")
        session.commit()

    class AI:
        async def coach(self, request):
            assert request.budget_context["budget_periods"] == [str(OCT), str(NOV)]
            return response(command("delete", {"kind": "periods", "periods": [str(NOV)]}))

    app.dependency_overrides[get_ai_service_client] = AI
    try:
        with TestClient(app) as client:
            listing = client.get("/api/users/budget-u/budgets", headers=HEADERS)
            assert listing.status_code == 200
            assert len(listing.json()["rows"]) == 2
            assert (
                client.get(
                    "/api/users/budget-u/budgets?start=2026-10-02&end=2026-12-01", headers=HEADERS
                ).status_code
                == 422
            )
            payload = {
                "user_id": "budget-u",
                "session_id": "budget-chat",
                "message": "Delete my November 2026 budget",
                "budget_period_start": str(OCT),
            }
            assert (
                client.post("/api/coach", json=payload, headers=HEADERS).json()["audit"][
                    "action_status"
                ]
                == "preview"
            )
            payload["message"] = "confirm budget"
            assert (
                client.post("/api/coach", json=payload, headers=HEADERS).json()["audit"][
                    "action_status"
                ]
                == "saved"
            )
        with db_session_factory() as session:
            assert (
                next(
                    session.scalars(
                        select(MonthlyBudgetRecord).where(MonthlyBudgetRecord.user_id == "budget-u")
                    )
                ).period_start
                == OCT
            )
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


def test_budget_status_range_uses_requested_months_instead_of_ui_default(db_session_factory):
    with db_session_factory() as session:
        save(session, OCT)
        save(session, NOV, savings=900)
        session.commit()

    class AI:
        async def coach(self, request):
            return CoachResponse(
                session_id=request.session_id,
                selected_agents=["budget"],
                answer="Checking",
                agent_results=[],
                disclaimers=[],
                audit={
                    "turn_decision": {
                        "budget_status_query": True,
                        "budget_scope": {"kind": "range", "start": str(OCT), "end": str(NOV)},
                    }
                },
            )

    app.dependency_overrides[get_ai_service_client] = AI
    try:
        with TestClient(app) as client:
            result = client.post(
                "/api/coach",
                headers=HEADERS,
                json={
                    "user_id": "budget-u",
                    "session_id": "budget-chat",
                    "message": "Am I over budget from October through November 2026?",
                    "budget_period_start": str(DEC),
                },
            ).json()
            assert "2026-10" in result["answer"] and "2026-11" in result["answer"]
            assert "2026-12" not in result["answer"]
            assert "1,600.00" in result["answer"]
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)
