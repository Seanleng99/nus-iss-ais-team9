import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.financial_schemas import BudgetUpsert, TransactionCreate
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import (
    SQLAlchemyBudgetRepository,
    SQLAlchemyChatRepository,
    SQLAlchemyTransactionRepository,
)
from app.main import app
from app.services.budget_capture import handle_budget_confirmation, stage_budget_draft
from app.services.budget_constraints import AllocationPolicy, requirements, save_policy
from app.services.budget_reconciliation import (
    MatchRequest,
    UnlinkRequest,
    links,
    save_match,
    save_settings,
    unlink,
)
from app.services.budget_workspace import WorkspaceChange, confirm_change, preview_change
from app.services.cashflow import CashflowSettings, project_cashflow
from app.services.financial_workspace import read_section


def config():
    return {
        "opening_on": "2026-09-01",
        "opening_balance": 2000,
        "currency": "SGD",
        "schedules": [
            {
                "id": "rent",
                "name": "Rent",
                "kind": "expense",
                "category": "housing",
                "amount": 1500,
                "first_on": "2026-09-05",
                "frequency": "monthly",
            }
        ],
    }


def setup(session):
    save_settings(session, "u", CashflowSettings(**config(), confirmed=True))


def txn(session, amount=600, kind="expense", owner="u", day="2026-09-05"):
    return SQLAlchemyTransactionRepository(session).create(
        owner,
        TransactionCreate(
            description="Rent payment" if kind == "expense" else "Rent refund",
            category="housing",
            amount={"amount": amount},
            occurred_on=day,
            transaction_type=kind,
        ),
    )


def match(row, amount=600, **updates):
    return MatchRequest(
        transaction_id=row.id,
        schedule_id="rent",
        due_on="2026-09-05",
        amount=amount,
        spending_treatment="cash_only",
        effect=updates.pop("effect", "payment"),
        **updates,
    )


def change(op, payload):
    return WorkspaceChange(operation=op, payload_json=json.dumps(payload))


def test_partial_split_payments_and_refunds_never_double_count(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        payment = txn(session)
        save_match(session, "u", match(payment))
        result = project_cashflow(session, "u", date(2026, 9, 30), today=date(2026, 9, 30))
        assert result["closing_balance"] == 500
        assert result["days"][4]["scheduled"][0]["amount"] == 900
        refund = txn(session, 100, "refund", day="2026-09-06")
        save_match(session, "u", match(refund, 100, effect="refund_reduces_due"))
        assert project_cashflow(session, "u", date(2026, 9, 30))["closing_balance"] == 600
        refund2 = txn(session, 100, "refund", day="2026-09-07")
        save_match(session, "u", match(refund2, 100, effect="refund_reopens"))
        assert project_cashflow(session, "u", date(2026, 9, 30))["closing_balance"] == 600
        with pytest.raises(ValueError, match="unallocated"):
            save_match(session, "u", match(payment, 1))
        with pytest.raises(ValueError, match="refund"):
            save_match(
                session, "u", match(txn(session, 1000, "refund"), 1000, effect="refund_reopens")
            )


def test_overpayment_ownership_type_and_occurrence_validation(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        with pytest.raises(ValueError, match="exceed"):
            save_match(session, "u", match(txn(session, 1600), 1600))
        for record in [txn(session, owner="other"), txn(session, kind="refund")]:
            with pytest.raises(ValueError, match="owned"):
                save_match(session, "u", match(record))
        request = match(txn(session))
        request.due_on = date(2026, 9, 7)
        with pytest.raises(ValueError, match="occurrence"):
            save_match(session, "u", request)


def test_guard_linked_records_and_refund_dependencies(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        payment = txn(session)
        link = save_match(session, "u", match(payment))
        with pytest.raises(ValueError, match="matches"):
            SQLAlchemyTransactionRepository(session).delete("u", payment.id)
        altered = CashflowSettings(**config(), confirmed=True)
        altered.schedules[0].amount = 1200
        with pytest.raises(ValueError, match="terms"):
            save_settings(session, "u", altered)
        altered = CashflowSettings(**config(), confirmed=True)
        altered.schedules[0].settled_dates = [date(2026, 9, 5)]
        with pytest.raises(ValueError, match="manually settled"):
            save_settings(session, "u", altered)
        refund_link = save_match(
            session, "u", match(txn(session, 100, "refund"), 100, effect="refund_reopens")
        )
        with pytest.raises(ValueError, match="refund"):
            unlink(session, "u", UnlinkRequest(link_id=link["id"]))
        unlink(session, "u", UnlinkRequest(link_id=refund_link["id"]))
        unlink(session, "u", UnlinkRequest(link_id=link["id"]))
        assert SQLAlchemyTransactionRepository(session).delete("u", payment.id)


def test_separate_obligations_add_and_legacy_requires_review(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        SQLAlchemyBudgetRepository(session).upsert(
            "u",
            BudgetUpsert(
                period_start="2026-09-01",
                categories=[{"category": "housing", "limit_amount": 2000}],
                planning={"take_home_income": 3000, "savings_target": 500},
            ),
        )
        base = {
            "period_start": "2026-09-01",
            "confirmed": True,
            "minimum_savings": 0,
            "max_reduction_percent": 100,
            "protected_categories": [],
            "category_floors": {},
            "goals": [],
        }
        debt = {"name": "Loan", "category": "housing", "balance": 5000, "minimum_payment": 300}
        with pytest.raises(ValueError, match="separate obligation"):
            save_policy(session, "u", AllocationPolicy(**base, debts=[debt]))
        save_policy(
            session, "u", AllocationPolicy(**base, debts=[{**debt, "separate_obligation": True}])
        )
        assert requirements(session, "u", date(2026, 9, 1))["floors"]["housing"] == 180000
        save_policy(session, "u", AllocationPolicy(**base, debts=[{**debt, "schedule_id": "rent"}]))
        assert requirements(session, "u", date(2026, 9, 1))["floors"]["housing"] == 150000
        empty = CashflowSettings(**{**config(), "schedules": []}, confirmed=True)
        with pytest.raises(ValueError, match="linked debt"):
            save_settings(session, "u", empty)


def test_preview_is_read_only_and_stale_or_expired_cannot_confirm(db_session_factory):
    with db_session_factory() as session:
        proposal = preview_change(session, "u", change("cashflow", config()))
        assert read_section(session, "u", "cashflow") is None
        confirm_change(session, "u", proposal)
        proposal = preview_change(session, "u", change("cashflow", {"opening_balance": 3000}))
        txn(session)
        with pytest.raises(ValueError, match="changed"):
            confirm_change(session, "u", proposal)
        proposal = preview_change(session, "u", change("cashflow", {"opening_balance": 3000}))
        proposal["expires_at"] = "2020-01-01T00:00:00+00:00"
        with pytest.raises(ValueError, match="expired"):
            confirm_change(session, "u", proposal)
        assert read_section(session, "u", "cashflow")["opening_balance"] == 2000


@pytest.mark.parametrize(
    "op,payload,missing",
    [
        ("cashflow", {"opening_on": "2026-09-01"}, "opening balance"),
        ("cashflow", {"opening_on": "2026-09-01", "opening_balance": 0}, "currency"),
        ("commitments", {}, "month and year"),
        ("continuity", {}, "every target month"),
        ("reconcile", {}, "transaction_id"),
        ("reviews", {"enabled": True}, "cadence"),
    ],
)
def test_missing_details_are_not_assumed(db_session_factory, op, payload, missing):
    with db_session_factory() as session:
        with pytest.raises(ValueError, match=missing):
            preview_change(session, "u", change(op, payload))
        assert read_section(session, "u", "cashflow") is None


def stage(session, chat, op, payload, **updates):
    draft = {"action": "workspace", "workspace": change(op, payload).model_dump(), **updates}
    response = CoachResponse(
        session_id=chat.id,
        selected_agents=["budget"],
        answer="draft",
        disclaimers=[],
        audit={},
        agent_results=[{"agent": "budget", "summary": "draft", "data": {"budget_draft": draft}}],
    )
    stage_budget_draft(session, "u", chat, response)
    session.flush()
    return response


def confirm(session, message="confirm budget", chat_id="chat"):
    return handle_budget_confirmation(
        session, CoachRequest(user_id="u", session_id=chat_id, message=message)
    )


def test_coach_clarify_correct_confirm_cancel_and_isolation(db_session_factory):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u", "chat", "Budget")
        response = stage(session, chat, "cashflow", {})
        assert "opening date" in response.answer or "opening on" in response.answer
        assert not chat.pending_budget["ready"]
        assert "missing" in confirm(session).answer
        response = stage(session, chat, "cashflow", config())
        assert "Rent" in response.answer and "SGD 1,500.00" in response.answer
        assert read_section(session, "u", "cashflow") is None
        assert "no pending" in confirm(session, chat_id="other").answer
        response = stage(session, chat, "cashflow", {**config(), "opening_balance": 2500})
        assert "SGD 2,500.00" in response.answer
        assert "Saved" in confirm(session).answer
        assert read_section(session, "u", "cashflow")["opening_balance"] == 2500
        assert "no pending" in confirm(session).answer
        stage(session, chat, "cashflow", {"opening_balance": 4000})
        assert "cancelled" in confirm(session, "cancel").answer
        assert read_section(session, "u", "cashflow")["opening_balance"] == 2500


def test_workspace_api_preview_confirm_and_replay(db_session_factory):
    from app.core.config import settings

    with TestClient(app, headers={"X-API-Key": settings.api_key}) as client:
        response = client.post(
            "/api/users/u/budget/workspace/preview", json=change("cashflow", config()).model_dump()
        )
        assert response.status_code == 200, response.text
        preview = response.json()
        assert client.get("/api/users/u/cashflow/settings").json() is None
        payload = {"preview_id": preview["preview_id"], "confirmed": True}
        assert (
            client.post("/api/users/other/budget/workspace/confirm", json=payload).status_code
            == 409
        )
        assert client.post("/api/users/u/budget/workspace/confirm", json=payload).status_code == 200
        assert client.post("/api/users/u/budget/workspace/confirm", json=payload).status_code == 409


def test_coach_multi_month_preview_is_separate_from_ui_and_saves_atomically(db_session_factory):
    with db_session_factory() as session:
        SQLAlchemyBudgetRepository(session).upsert(
            "u",
            BudgetUpsert(
                period_start="2026-09-01",
                categories=[{"category": "food", "limit_amount": 500}],
                planning={"take_home_income": 3000, "savings_target": 500},
            ),
        )
        chat = SQLAlchemyChatRepository(session).create("u", "chat", "Budget")
        payload = {
            "source_period": "2026-09-01",
            "first_period": "2026-10-01",
            "months": 2,
            "take_home_income": 3000,
            "savings_target": 500,
            "carry_rule": "copy_limits",
            "coverage_confirmed": True,
        }
        response = stage(session, chat, "continuity", payload)
        assert "2026-11-01" in response.answer
        assert read_section(session, "u", "pending_batch") is None
        assert SQLAlchemyBudgetRepository(session).get("u", date(2026, 10, 1)) is None
        assert "Saved" in confirm(session).answer
        assert SQLAlchemyBudgetRepository(session).get("u", date(2026, 11, 1)) is not None


def test_refund_cannot_precede_the_payment_it_reverses(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        save_match(session, "u", match(txn(session, day="2026-09-10")))
        refund = txn(session, 100, "refund", day="2026-09-05")
        with pytest.raises(ValueError, match="refund"):
            save_match(session, "u", match(refund, 100, effect="refund_reopens"))


def test_one_payment_can_split_between_two_bill_occurrences(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        payment = txn(session, 2000)
        save_match(session, "u", match(payment, 1500))
        request = match(payment, 500)
        request.due_on = date(2026, 10, 5)
        save_match(session, "u", request)
        result = project_cashflow(session, "u", date(2026, 10, 31), today=date(2026, 9, 30))
        assert result["closing_balance"] == -1000
        assert len(links(session, "u")) == 2


def test_workspace_correction_disarms_prior_preview_and_unrelated_reply_cannot_save(
    db_session_factory,
):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u", "chat", "Budget")
        stage(session, chat, "cashflow", config())
        stage(session, chat, "cashflow", {}, questions=["Which opening date?"])
        assert not chat.pending_budget["ready"]
        assert "missing" in confirm(session).answer
        assert read_section(session, "u", "cashflow") is None
        stage(session, chat, "cashflow", config())
        stage_budget_draft(
            session,
            "u",
            chat,
            CoachResponse(
                session_id="chat",
                selected_agents=[],
                answer="Other topic",
                agent_results=[],
                disclaimers=[],
                audit={},
            ),
        )
        assert "missing" in confirm(session).answer
        assert read_section(session, "u", "cashflow") is None


def test_coach_http_workspace_clarification_and_confirmation(db_session_factory):
    from app.api.routes import get_ai_service_client
    from app.core.config import settings

    calls = []

    class BudgetAI:
        async def coach(self, request):
            calls.append(request)
            payload = {} if len(calls) == 1 else config()
            return CoachResponse(
                session_id=request.session_id,
                selected_agents=["budget"],
                answer="draft",
                disclaimers=[],
                audit={},
                agent_results=[
                    {
                        "agent": "budget",
                        "summary": "Draft",
                        "data": {
                            "budget_draft": {
                                "action": "workspace",
                                "workspace": change("cashflow", payload).model_dump(),
                            }
                        },
                    }
                ],
            )

    app.dependency_overrides[get_ai_service_client] = BudgetAI
    try:
        with TestClient(app, headers={"X-API-Key": settings.api_key}) as client:
            client.put("/api/users/u/profile", json={})

            def send(message):
                response = client.post(
                    "/api/coach", json={"user_id": "u", "session_id": "chat", "message": message}
                )
                assert response.status_code == 200, response.text
                return response.json()

            assert "Nothing has been saved" in send("Schedule a rent bill")["answer"]
            assert (
                "Review proposed"
                in send(
                    "SGD 1500 monthly from September 5, 2026; opening September 1, 2026 SGD 2000"
                )["answer"]
            )
            assert calls[-1].pending_budget["action"] == "workspace"
            assert "workspace" in calls[-1].budget_context
            assert client.get("/api/users/u/cashflow/settings").json() is None
            assert "Saved" in send("confirm budget")["answer"]
            assert len(calls) == 2
            assert (
                client.get("/api/users/u/cashflow/settings").json()["schedules"][0]["amount"]
                == 1500
            )
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


@pytest.mark.parametrize("message", [
    "Set my budget for October 2026 in SGD: housing 1500 and pet care 120. These are monthly expense limits. Ask me to confirm before saving.",
    "Plan my October 2026 budget in SGD. My gross monthly income is 4000 before deductions; I have not supplied my take-home income. Housing limit 1500, food limit 500, savings target 500. These are all my expenses.",
    "Set up my cash-flow plan in SGD: opening combined balance SGD 2000 at the start of September 1, 2026. My only schedule is a bill called Rent, expense category housing, SGD 1500 monthly starting September 5, 2026, with no end date and no manually settled dates. Preview it and ask me to confirm before saving.",
])
def test_budget_planning_is_not_intercepted_by_local_spending_handlers(message):
    from app.api.routes import get_ai_service_client
    from app.core.config import settings

    calls = []

    class BudgetAI:
        async def coach(self, request):
            calls.append(request)
            return CoachResponse(session_id=request.session_id, selected_agents=["budget"], answer="Budget agent reached", agent_results=[], disclaimers=[], audit={})

    app.dependency_overrides[get_ai_service_client] = BudgetAI
    try:
        with TestClient(app, headers={"X-API-Key": settings.api_key}) as client:
            response = client.post("/api/coach", json={"user_id": "u", "session_id": "route-budget", "message": message, "requested_agents": ["budget"]})
            assert response.status_code == 200
            assert response.json()["answer"] == "Budget agent reached"
            assert len(calls) == 1
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)
