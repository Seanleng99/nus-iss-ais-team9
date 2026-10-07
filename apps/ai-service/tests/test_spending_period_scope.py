"""Explicit analysis and comparison periods override the sidebar independently."""

import json

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


class PeriodGateway(LocalFixtureModelGateway):
    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            message = json.loads(kwargs["user_prompt"])["message"]
            return json.dumps({"selected_agents": ["spending", "budget"], "rationale": ["Independent period-specific tasks."],
                "task_assignments": [{"agent": "spending", "question": "Analyze November against October", "source_quotes": [message],
                                      "requires_spending": False},
                                     {"agent": "budget", "question": "Explain October confirmed savings", "source_quotes": [message],
                                      "requires_spending": False, "requires_income": True}],
                "budget_scope": {"kind": "periods", "periods": ["2026-10-01"]},
                "spending_scope": {"kind": "periods", "periods": ["2026-11-01", "2026-10-01"]},
                "spending_analysis_period": "2026-11-01"})
        return super().generate(**kwargs)


def test_missing_november_remains_primary_and_october_budget_is_independent():
    october = {"period_start": "2026-10-01", "category_totals": {"food": 660}, "transaction_count": 12,
               "currency": "SGD", "excluded_currencies": [], "first_recorded_on": "2026-10-01", "last_recorded_on": "2026-10-06"}
    capacity = {"source": "confirmed_plan", "period_start": "2026-10-01", "currency": "SGD",
                "estimated_savings_capacity": 1600, "take_home_income": 6500, "planned_expenses": 3950,
                "unallocated_income": 950, "budget_method": "flexible", "calculation_method": "Confirmed allocation"}
    request = CoachRequest(user_id="u", session_id="s",
        message="Analyze November 2026 compared with October 2026. Independently explain October confirmed savings.",
        snapshot={"period_start": "2026-10-01", "monthly_income": {"amount": 6500}},
        saved_budget_capacity=capacity,
        budget_context={"selected_period": "2026-10-01", "capacity_by_period": {"2026-10-01": capacity},
                        "spending_by_period": {"2026-10-01": october}})
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=PeriodGateway()).handle(request)
    spending = next(item for item in response.agent_results if item.agent == "spending")
    budget = next(item for item in response.agent_results if item.agent == "budget")
    assert spending.data["analysis_period_start"] == "2026-11-01"
    assert spending.data["transaction_count"] == 0 and spending.data["category_totals"] == {}
    assert spending.data["selected_month_coverage"]["record_count"] == 0
    assert spending.data["comparison_periods"] == [october]
    assert "savings" in budget.data, budget.data
    assert budget.data["savings"] == 1600 and budget.data["capacity"]["period_start"] == "2026-10-01"
    assert response.audit["dependency_edges"] == []
    route = next(event for event in response.audit["events"] if event["event_type"] == "routing.completed")
    assert route["details"]["after"]["spending_analysis_period"] == "2026-11-01"


def test_raw_records_are_partitioned_for_missing_requested_month():
    request = CoachRequest(user_id="u", session_id="s", message="Analyze November 2026 expense patterns.",
        snapshot={"period_start": "2026-10-01", "recent_transactions": [
            {"description": "Food", "category": "food", "amount": {"amount": 50}, "occurred_on": "2026-10-02"}]})
    response = AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture")).handle(request)
    spending = next(item for item in response.agent_results if item.agent == "spending")
    assert spending.data["analysis_period_start"] == "2026-11-01"
    assert spending.data["transaction_count"] == 0
