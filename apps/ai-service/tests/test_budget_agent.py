from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator


def test_budget_calculation_uses_income_after_recurring_expenses() -> None:
    request = CoachRequest(
        user_id="u1",
        session_id="s1",
        message="Create a monthly budget",
        snapshot={
            "monthly_income": {"amount": 5000},
            "recurring_expenses": [
                {
                    "description": "Rent",
                    "category": "housing",
                    "amount": {"amount": 1500},
                    "occurred_on": "2026-08-01",
                },
                {
                    "description": "Phone",
                    "category": "utilities",
                    "amount": {"amount": 80},
                    "occurred_on": "2026-08-01",
                },
            ],
        },
    )
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=LocalFixtureModelGateway(),
    ).handle(request)
    budget = response.agent_results[0].data
    assert budget["disposable_income"] == 3420
    assert budget["needs"] == 1710
    assert budget["wants"] == 1026
    assert budget["savings"] == 684
