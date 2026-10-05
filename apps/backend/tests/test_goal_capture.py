from datetime import UTC, datetime, timedelta

import pytest
from coach_i18n import translate

from app.api.financial_schemas import GoalCreate
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import SQLAlchemyChatRepository, SQLAlchemyGoalRepository
from app.services.goal_capture import handle_goal_confirmation, stage_goal_draft


def draft(**changes):
    return dict(
        action="create",
        name="Emergency fund",
        currency="SGD",
        target_amount=12000,
        current_amount=1000,
        target_months=12,
        **changes,
    )


def stage(session, data, chat=None, blocked=False, locale=None):
    chat = chat or SQLAlchemyChatRepository(session).create("u1", "goals-chat", "Goals")
    reply = CoachResponse(
        session_id=chat.id,
        selected_agents=["goal_strategy"],
        answer="proposal",
        blocked=blocked,
        disclaimers=[],
        audit={"response_locale": locale} if locale else {},
        agent_results=[
            {"agent": "goal_strategy", "summary": "draft", "data": {"goal_draft": data}}
        ],
    )
    stage_goal_draft(session, "u1", chat, reply)
    session.commit()
    return chat, reply


def confirm(session, message="confirm goal", user="u1", conversation="goals-chat"):
    return handle_goal_confirmation(
        session, CoachRequest(user_id=user, session_id=conversation, message=message)
    )


def test_create_edit_delete_require_preview_and_confirmation(db_session_factory):
    with db_session_factory() as session:
        repo = SQLAlchemyGoalRepository(session)
        chat, reply = stage(session, draft())
        assert "Create goal preview" in reply.answer
        assert reply.audit["action_status"] == "preview"
        assert repo.list_records("u1") == []
        saved = confirm(session)
        assert "Saved" in saved.answer
        assert saved.audit == {"source": "goal_confirmation", "action_status": "saved"}
        session.commit()
        goal = repo.list_records("u1")[0]
        no_pending = confirm(session)
        assert "no pending" in no_pending.answer
        assert no_pending.audit["action_status"] == "no_pending"
        chat, reply = stage(
            session, {"action": "update", "goal_name": goal.name, "target_amount": 15000}, chat
        )
        assert "Before:" in reply.answer and "After:" in reply.answer
        assert float(goal.target_amount) == 12000
        assert "Saved" in confirm(session).answer
        session.commit()
        assert float(goal.target_amount) == 15000 and float(goal.current_amount) == 1000
        chat, reply = stage(session, {"action": "delete", "goal_name": goal.name}, chat)
        assert "permanently delete" in reply.answer
        assert len(repo.list_records("u1")) == 1
        deleted = confirm(session)
        assert "Deleted" in deleted.answer
        assert deleted.audit["action_status"] == "deleted"
        session.commit()
        assert repo.list_records("u1") == []
        assert "no pending" in confirm(session).answer


def test_chinese_goal_preview_and_confirmation_preserve_authoritative_values(db_session_factory):
    with db_session_factory() as session:
        _, reply = stage(session, draft(), locale="zh-Hans")
        assert translate("goal_action.create_preview", "zh-Hans") in reply.answer
        assert "SGD 12,000.00" in reply.answer and "Emergency fund" in reply.answer
        assert "currently saved" not in reply.answer
        assert SQLAlchemyGoalRepository(session).list_records("u1") == []
        response = handle_goal_confirmation(session, CoachRequest(
            user_id="u1", session_id="goals-chat", message="confirm goal", response_locale="zh-Hans",
        ))
        assert response.answer == translate("goal_action.saved", "zh-Hans")
        session.commit()
        assert float(SQLAlchemyGoalRepository(session).list_records("u1")[0].target_amount) == 12000


def test_chinese_goal_missing_fields_do_not_claim_saved_result(db_session_factory):
    with db_session_factory() as session:
        data = draft()
        data.pop("current_amount")
        data.pop("target_months")
        _, reply = stage(session, data, locale="zh-Hans")
        assert translate("goal_action.current", "zh-Hans") in reply.answer
        assert translate("goal_action.duration", "zh-Hans") in reply.answer
        assert "Please provide" not in reply.answer
        assert SQLAlchemyGoalRepository(session).list_records("u1") == []


@pytest.mark.parametrize(
    "field", ["current_amount", "target_amount", "target_months", "name"]
)
def test_missing_fields_never_save(db_session_factory, field):
    with db_session_factory() as session:
        data = draft()
        data.pop(field)
        _, reply = stage(session, data)
        assert "Please provide" in reply.answer
        assert reply.audit["action_status"] == "needs_input"
        missing = confirm(session)
        assert "Please provide" in missing.answer
        assert missing.audit["action_status"] == "needs_input"
        assert SQLAlchemyGoalRepository(session).list_records("u1") == []


@pytest.mark.parametrize("currency", [{}, {"currency": None}])
def test_goal_currency_defaults_to_sgd_and_edits_preserve_it(db_session_factory, currency):
    with db_session_factory() as session:
        data = draft()
        data.pop("currency")
        data.update(currency)
        chat, reply = stage(session, data)
        assert "Create goal preview" in reply.answer
        assert "target SGD 12,000.00" in reply.answer
        assert "Saved" in confirm(session).answer
        session.commit()
        goal = SQLAlchemyGoalRepository(session).list_records("u1")[0]
        assert goal.currency == "SGD"
        _, reply = stage(session, {"action": "update", "goal_name": goal.name, "current_amount": 2000}, chat)
        assert "currently saved SGD 2,000.00" in reply.answer
        assert "Saved" in confirm(session).answer
        session.commit()
        assert goal.currency == "SGD" and float(goal.current_amount) == 2000


def test_foreign_goal_currency_never_saves(db_session_factory):
    with db_session_factory() as session:
        data = draft()
        data["currency"] = "USD"
        _, reply = stage(session, data)
        assert "SGD only" in reply.answer
        assert "SGD only" in confirm(session).answer
        assert SQLAlchemyGoalRepository(session).list_records("u1") == []


def test_cancel_and_owner_conversation_isolation(db_session_factory):
    with db_session_factory() as session:
        stage(session, draft())
        assert "no pending" in confirm(session, user="other").answer
        assert "no pending" in confirm(session, conversation="other").answer
        assert confirm(session, "yes") is None
        cancelled = confirm(session, "cancel goal")
        assert "cancelled" in cancelled.answer
        assert cancelled.audit == {"source": "goal_confirmation", "action_status": "cancelled"}
        assert "no pending" in confirm(session).answer


@pytest.mark.parametrize("expired", [True, False])
def test_stale_preview_requires_reconfirmation(db_session_factory, expired):
    with db_session_factory() as session:
        chat, _ = stage(session, draft())
        chat.pending_goal = {
            **chat.pending_goal,
            **(
                {"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
                if expired
                else {"ready": False}
            ),
        }
        assert "fresh preview" in confirm(session).answer
        assert SQLAlchemyGoalRepository(session).list_records("u1") == []
        assert "Saved" in confirm(session).answer


def test_changed_goal_and_ambiguous_goal(db_session_factory):
    with db_session_factory() as session:
        repo = SQLAlchemyGoalRepository(session)
        chat, _ = stage(session, draft())
        confirm(session)
        session.commit()
        goal = repo.list_records("u1")[0]
        stage(session, {"action": "delete", "goal_name": goal.name}, chat)
        goal.current_amount = 2000
        session.commit()
        assert "fresh preview" in confirm(session).answer
        assert len(repo.list_records("u1")) == 1
        repo.create(
            "u1", GoalCreate(name=goal.name, target_amount={"amount": 500}, target_months=3)
        )
        _, reply = stage(session, {"action": "delete", "goal_name": goal.name}, chat)
        assert "No unique goal" in reply.answer
        assert str(goal.id) in reply.answer
        assert "No unique goal" in confirm(session).answer
        _, reply = stage(session, {"action": "delete", "goal_id": str(goal.id)}, chat)
        assert "Delete goal preview" in reply.answer


def test_blocked_invalid_and_foreign_id_cannot_stage(db_session_factory):
    with db_session_factory() as session:
        chat, _ = stage(session, draft(), blocked=True)
        assert chat.pending_goal is None
        _, reply = stage(session, {**draft(), "target_amount": float("inf")}, chat)
        assert "invalid" in reply.answer
        other = SQLAlchemyGoalRepository(session).create(
            "other", GoalCreate(name="Private", target_amount={"amount": 500}, target_months=3)
        )
        _, reply = stage(session, {"action": "delete", "goal_id": str(other.id)}, chat)
        assert "Private" not in reply.answer
        assert "No unique goal" in confirm(session).answer


def test_confirmation_rollback_is_atomic(db_session_factory):
    with db_session_factory() as session:
        stage(session, draft())
        assert "Saved" in confirm(session).answer
        session.rollback()
    with db_session_factory() as session:
        assert SQLAlchemyGoalRepository(session).list_records("u1") == []
        assert "Saved" in confirm(session).answer
        session.commit()


def test_deleted_target_cannot_be_confirmed(db_session_factory):
    with db_session_factory() as session:
        chat, _ = stage(session, draft())
        confirm(session)
        session.commit()
        repo = SQLAlchemyGoalRepository(session)
        goal = repo.list_records("u1")[0]
        stage(session, {"action": "update", "goal_id": str(goal.id), "current_amount": 500}, chat)
        repo.delete("u1", goal.id)
        session.commit()
        assert "No unique goal" in confirm(session).answer
        assert repo.list_records("u1") == []


def test_coach_http_goal_lifecycle():
    from fastapi.testclient import TestClient

    from app.api.routes import get_ai_service_client
    from app.core.config import settings
    from app.main import app

    calls = []
    proposals = [
        {**draft(), "current_amount": None},
        draft(),
        {"action": "update", "goal_name": "Emergency fund", "current_amount": 2000},
        {"action": "delete", "goal_name": "Emergency fund"},
    ]

    class GoalAI:
        async def coach(self, request):
            calls.append(request)
            return CoachResponse(
                session_id=request.session_id,
                selected_agents=["goal_strategy"],
                answer="proposal",
                disclaimers=[],
                audit={},
                agent_results=[
                    {
                        "agent": "goal_strategy",
                        "summary": "unsaved",
                        "data": {"goal_draft": proposals[len(calls) - 1]},
                    }
                ],
            )

    app.dependency_overrides[get_ai_service_client] = GoalAI
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    try:
        client.put("/api/users/u1/profile", headers=headers, json={})

        def send(message):
            result = client.post(
                "/api/coach",
                headers=headers,
                json={"user_id": "u1", "session_id": "goal-http", "message": message},
            )
            assert result.status_code == 200, result.text
            return result.json()["answer"]

        def goals():
            result = client.get("/api/users/u1/goals", headers=headers)
            assert result.status_code == 200
            return result.json()

        assert "currently saved" in send("Create an emergency fund goal")
        assert goals() == []
        assert "Create goal preview" in send("I already saved SGD 1000")
        assert calls[-1].pending_goal["name"] == "Emergency fund"
        assert goals() == []
        assert "Saved" in send("confirm goal")
        assert len(calls) == 2 and len(goals()) == 1
        assert "Before:" in send("Update my emergency fund goal savings to SGD 2000")
        assert goals()[0]["current_amount"]["amount"] == 1000
        assert "Saved" in send("confirm goal")
        assert goals()[0]["current_amount"]["amount"] == 2000
        assert "Delete goal preview" in send("Delete my emergency fund goal")
        assert len(goals()) == 1
        assert "Deleted" in send("confirm goal")
        assert goals() == [] and len(calls) == 4
        assert "no pending" in send("confirm goal")
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


@pytest.mark.parametrize(
    "message",
    [
        "estimate my upcoming spending based on my recurring expenses",
        "can you help me add my Spotify monthly subscription that costs 10.90",
    ],
)
def test_pending_goal_followups_are_not_intercepted_by_new_shortcuts(db_session_factory, message):
    from fastapi.testclient import TestClient

    from app.api.routes import get_ai_service_client
    from app.core.config import settings
    from app.main import app

    calls = []

    class NoChangeAI:
        async def coach(self, request):
            calls.append(request)
            return CoachResponse(
                session_id=request.session_id,
                selected_agents=["goal_strategy"],
                answer="Clarification only",
                agent_results=[],
                disclaimers=[],
                audit={},
            )

    with db_session_factory() as session:
        stage(session, draft())
    app.dependency_overrides[get_ai_service_client] = NoChangeAI
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    try:

        def send(text):
            response = client.post(
                "/api/coach",
                headers=headers,
                json={"user_id": "u1", "session_id": "goals-chat", "message": text},
            )
            assert response.status_code == 200, response.text
            return response.json()

        assert send(message)["answer"] == "Clarification only"
        assert calls[0].pending_goal["name"] == "Emergency fund"
        assert "fresh preview" in send("confirm goal")["answer"]
        assert client.get("/api/users/u1/goals", headers=headers).json() == []
        assert client.get("/api/users/u1/transactions", headers=headers).json() == []
        assert "Saved" in send("confirm goal")["answer"]
        assert len(calls) == 1
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)


def test_new_goal_request_with_monthly_expenses_is_not_a_forecast():
    from fastapi.testclient import TestClient

    from app.api.routes import get_ai_service_client
    from app.core.config import settings
    from app.main import app

    class GoalAI:
        async def coach(self, request):
            return CoachResponse(
                session_id=request.session_id,
                selected_agents=["goal_strategy"],
                answer="proposal",
                disclaimers=[],
                audit={},
                agent_results=[
                    {
                        "agent": "goal_strategy",
                        "summary": "unsaved",
                        "data": {"goal_draft": {**draft(), "name": "Monthly expenses"}},
                    }
                ],
            )

    app.dependency_overrides[get_ai_service_client] = GoalAI
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    try:
        client.put("/api/users/u1/profile", headers=headers, json={})
        result = client.post(
            "/api/coach",
            headers=headers,
            json={
                "user_id": "u1",
                "session_id": "goals-chat",
                "message": "Create a goal named Monthly expenses, target SGD 12000, saved SGD 1000, over 12 months.",
            },
        )
        assert result.status_code == 200, result.text
        assert "Create goal preview" in result.json()["answer"]
        assert client.get("/api/users/u1/goals", headers=headers).json() == []
    finally:
        app.dependency_overrides.pop(get_ai_service_client, None)
