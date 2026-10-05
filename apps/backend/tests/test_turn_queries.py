from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import settings
from app.domain.schemas import CoachResponse
from app.domain.turn_queries import TurnQueries
from app.infrastructure.models import ChatSessionRecord
from app.main import app


def test_typed_budget_query_retains_missing_period():
    query = TurnQueries.model_validate({"budget_status_query": True,
                                       "missing_fields": ["budget_period_start"]})
    assert query.missing_fields == ["budget_period_start"]
    with pytest.raises(ValueError):
        TurnQueries.model_validate({"missing_fields": ["unknown_field"]})


@pytest.mark.parametrize("selected_period", [None, "2026-10-01"])
def test_ambiguous_budget_month_asks_before_any_saved_status_lookup(
    monkeypatch, db_session_factory, selected_period,
):
    class StatusAI:
        async def coach(self, request):
            return CoachResponse(
                session_id=request.session_id, selected_agents=["budget"],
                answer="The requested month needs clarification.", agent_results=[], disclaimers=[],
                audit={"turn_decision": {"budget_status_query": True,
                                         "missing_fields": ["budget_period_start"]}},
            )

    def unexpected_lookup(*args):
        pytest.fail("An ambiguous requested period must not select any saved budget")

    monkeypatch.setitem(app.dependency_overrides, routes.get_ai_service_client, lambda: StatusAI())
    monkeypatch.setattr(routes, "build_status_reply", unexpected_lookup)
    request = {"user_id": "synthetic-period", "session_id": "ambiguous-period",
               "message": "Did I exceed my March budget?"}
    if selected_period:
        request["budget_period_start"] = selected_period
    with TestClient(app) as client:
        response = client.post("/api/coach", headers={"X-API-Key": settings.api_key}, json=request)

    assert response.status_code == 200
    result = response.json()
    assert "month and year" in result["answer"]
    assert result["audit"]["turn_decision"]["missing_fields"] == ["budget_period_start"]
    assert any(item["data"].get("needs_input") for item in result["agent_results"])
    with db_session_factory() as db:
        state = db.get(ChatSessionRecord, "ambiguous-period").conversation_state
        assert state["pending_action"] == "budget_status"
        assert state["pending_fields"] == ["budget_period_start"]


@pytest.mark.parametrize("explicit_period", [None, "2025-03-01"])
def test_unambiguous_budget_status_uses_selected_period_or_current_month(monkeypatch, explicit_period):
    class StatusAI:
        async def coach(self, request):
            return CoachResponse(
                session_id=request.session_id, selected_agents=["budget"], answer="Reviewed status.",
                agent_results=[], disclaimers=[],
                audit={"turn_decision": {"budget_status_query": True,
                                         "budget_status_period_start": explicit_period}},
            )

    periods = []

    def recorded_status(session, user_id, period):
        periods.append(period)
        return f"Checked saved budget for {period.isoformat()}."

    monkeypatch.setitem(app.dependency_overrides, routes.get_ai_service_client, lambda: StatusAI())
    monkeypatch.setattr(routes, "build_status_reply", recorded_status)
    monkeypatch.setattr(routes, "_current_period_start", lambda: date(2026, 10, 1))
    with TestClient(app) as client:
        response = client.post("/api/coach", headers={"X-API-Key": settings.api_key}, json={
            "user_id": "synthetic-period", "session_id": "known-period",
            "message": "Did I exceed my March 2025 budget?" if explicit_period else "Am I over budget this month?",
        })

    assert response.status_code == 200
    expected = date.fromisoformat(explicit_period) if explicit_period else date(2026, 10, 1)
    assert periods == [expected]
    assert expected.isoformat() in response.json()["answer"]
