import json

import pytest

from app.core.config import Settings
from app.core.schemas import AgentName, AgentTask, CoachRequest, RouterDecision
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
from app.tools.budget_context import scope_budget_request


def orchestrator(gateway=None):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway)


def txn(period, amount=100):
    return {
        "description": "Recorded expense",
        "category": "food",
        "amount": {"amount": amount},
        "occurred_on": period,
    }


def request(**changes):
    return CoachRequest(
        user_id="u",
        session_id="s",
        message="Where could I adjust my budget?",
        snapshot={
            "period_start": "2026-10-01",
            "monthly_income": {"amount": 4000},
            "recent_transactions": [txn("2026-10-02")],
        },
        budget_context={
            "selected_period": "2026-10-01",
            "budget_periods": ["2026-09-01", "2026-11-01"],
            "budgets_by_period": {
                "2026-11-01": {
                    "period_start": "2026-11-01",
                    "currency": "SGD",
                    "categories": {"food": 600},
                    "restrictions": {"category_minimums": {"food": 200}, "savings_minimum": 100},
                }
            },
            "spending_by_period": {
                p: {
                    "period_start": p,
                    "currency": "SGD",
                    "category_totals": {"food": amount},
                    "transaction_count": 1,
                }
                for p, amount in [("2026-09-01", 300), ("2026-10-01", 100), ("2026-11-01", 200)]
            },
            "workspace": {"unrelated": "do not expose to ordinary advice"},
        },
        **changes,
    )


def tasks(scope):
    o = orchestrator()
    scoped = scope_budget_request(
        request(),
        RouterDecision(selected_agents=["budget"], rationale=["Advice"], budget_scope=scope),
    )
    state = {
        "request": scoped,
        "sanitized_message": "Use my spending patterns to explain my budget",
    }
    return (
        o,
        scoped,
        o._create_task(state, AgentName.BUDGET),
        o._create_task(state, AgentName.SPENDING),
    )


def test_ordinary_advice_receives_categories_and_commitments_without_workspace():
    o, scoped, budget, spending = tasks({"kind": "periods", "periods": ["2026-11-01"]})
    context = o.agents[AgentName.BUDGET]._ground(budget, budget.sanitized_message)[
        "saved_budget_context"
    ]
    assert context["selected_budget"]["categories"] == {"food": 600}
    assert context["selected_budget"]["restrictions"]["category_minimums"] == {"food": 200}
    assert "workspace" not in budget.input_data["planning_context"]
    assert "spending_by_period" not in scoped.budget_context
    assert spending.input_data["period_start"] == "2026-11-01"
    assert spending.input_data["recent_transactions"] == []
    result = o.agents[AgentName.SPENDING]._ground(spending, spending.sanitized_message)
    assert result["category_totals"] == {"food": 200}
    assert result["analysis_period_start"] == "2026-11-01"


def test_range_totals_and_prior_history_are_separate():
    o, _, budget, spending = tasks({"kind": "range", "start": "2026-10-01", "end": "2026-12-01"})
    data = o.agents[AgentName.SPENDING]._ground(spending, spending.sanitized_message)
    assert data["category_totals"] == {"food": 300}
    assert [r["transaction_count"] for r in data["monthly_category_totals"]] == [1, 1, 0]
    assert data["historical_months"][0]["category_totals"] == {"food": 300}
    assert data["transaction_count"] == 2
    assert budget.input_data["planning_context"]["scoped_budgets"][-1]["status"] == "missing"


def test_all_saved_scope_excludes_expense_only_months():
    o, _, _, spending = tasks({"kind": "all"})
    data = o.agents[AgentName.SPENDING]._ground(spending, spending.sanitized_message)
    assert [r["period_start"] for r in data["monthly_category_totals"]] == [
        "2026-09-01",
        "2026-11-01",
    ]
    assert data["category_totals"] == {"food": 500}


def test_history_only_can_be_requested_and_is_published_by_spending():
    o = orchestrator()
    r = CoachRequest(
        user_id="u",
        session_id="s",
        message="Use my spending history to improve my budget",
        snapshot={
            "period_start": "2026-10-01",
            "monthly_income": {"amount": 4000},
            "historical_transactions": [txn("2026-09-02", 300)],
        },
    )
    state = {"request": r, "sanitized_message": r.message}
    budget = o._create_task(state, AgentName.BUDGET)
    assert (
        o.agents[AgentName.BUDGET]._preflight(budget, r.message).dependency_requests[0].capability.value
        == "transaction_category_totals"
    )
    spending = o._create_task(state, AgentName.SPENDING)
    data = o.agents[AgentName.SPENDING]._ground(spending, r.message)
    assert data["category_totals"] == {}
    assert data["historical_months"][0]["category_totals"] == {"food": 300}


def test_backend_history_only_remains_available_when_requested_month_is_empty():
    r = CoachRequest(
        user_id="u", session_id="aggregate-history-only",
        message="Use my spending history to improve my budget",
        requested_agents=["budget"],
        snapshot={"period_start": "2026-10-01", "monthly_income": {"amount": 4000}},
        budget_context={
            "selected_period": "2026-10-01",
            "spending_by_period": {
                "2026-09-01": {
                    "period_start": "2026-09-01", "category_totals": {"food": 300},
                    "transaction_count": 1, "currency": "SGD",
                },
            },
        },
    )

    response = orchestrator().handle(r)

    assert response.selected_agents == ["budget", "spending"]
    budget = next(result for result in response.agent_results if result.agent == "budget")
    spending = budget.data["spending_context"]
    assert spending["transaction_count"] == 0
    assert spending["category_totals"] == {}
    assert spending["historical_months"][0]["category_totals"] == {"food": 300}


class IntentGateway(LocalFixtureModelGateway):
    def __init__(self, requires_income=False):
        self.requires_income = requires_income
        self.calls = []

    def generate(self, **kw):
        self.calls.append(kw)
        if kw["system_prompt"].startswith("PROMPT_ID: budget_input_requirements"):
            return json.dumps({"requires_income": self.requires_income})
        return super().generate(**kw)


@pytest.mark.parametrize(
    "message",
    [
        "Explain how to calculate disposable income in general",
        "How do I build a budget?",
        "How much is usually saved in the 80/20 method?",
        "Explain how to build a budget and calculate savings in general",
    ],
)
def test_conceptual_questions_use_intent_without_requiring_personal_income(message):
    gateway = IntentGateway()
    agent = orchestrator(gateway).agents[AgentName.BUDGET]
    task = AgentTask(agent=AgentName.BUDGET, sanitized_message=message)
    assert agent._preflight(task, message) is None
    assert agent._ground(task, message)["calculation_status"] == "no_financial_inputs"
    assert len(gateway.calls) == 1


def test_personal_capacity_still_requires_income_and_goals_cannot_skip_it():
    agent = orchestrator(IntentGateway(True)).agents[AgentName.BUDGET]
    task = AgentTask(agent=AgentName.BUDGET, sanitized_message="Assess what I can afford")
    assert agent._preflight(task, task.sanitized_message).status == "needs_input"
    dependency = AgentTask(
        agent=AgentName.BUDGET,
        requested_by=AgentName.GOAL_STRATEGY,
        sanitized_message="Explain my goals",
    )
    assert agent._preflight(dependency, dependency.sanitized_message).status == "needs_input"


def test_unknown_recurring_terms_are_unavailable_instead_of_false_zero_capacity():
    o = orchestrator()
    task = AgentTask(
        agent=AgentName.BUDGET,
        sanitized_message="Assess my budget",
        input_data={
            "monthly_income": {"amount": 4000},
            "period_start": "2026-10-01",
            "recurring_expenses": [txn("2026-09-01", 1500), txn("2026-10-01", 1500)],
        },
        context_features={"has_monthly_income": True},
    )
    data = o.agents[AgentName.BUDGET]._ground(task, task.sanitized_message)
    assert data["capacity"]["source"] == "unavailable"
    assert data["disposable_income"] is None
    assert data["capacity"]["estimated_savings_capacity"] is None
    assert o.agents[AgentName.BUDGET]._capabilities(task, data, None)[0].evidence_refs == []


def test_unknown_recurring_capacity_reaches_goal_as_missing_information():
    response = orchestrator().handle(
        CoachRequest(
            user_id="u",
            session_id="s",
            message="Can I reach my course goal?",
            requested_agents=["goal_strategy"],
            snapshot={
                "period_start": "2026-10-01",
                "monthly_income": {"amount": 4000},
                "recurring_expenses": [txn("2026-09-01", 1500)],
                "goals": [
                    {"name": "Course", "target_amount": {"amount": 1200}, "target_months": 12}
                ],
            },
        )
    )
    assert not response.blocked
    goal = next(r for r in response.agent_results if r.agent == AgentName.GOAL_STRATEGY)
    assert goal.data["monthly_savings_capacity"]["source"] == "unavailable"
    assert goal.data["needs_input"] is True
    assert "feasibility" not in goal.data


def test_writer_receives_saved_categories_for_a_normal_advisory_turn():
    gateway = IntentGateway()
    r = request().model_copy(update={"message": "Explain my November 2026 budget choices."})
    response = orchestrator(gateway).handle(r)
    assert not response.blocked
    calls = [c for c in gateway.calls if c["system_prompt"].startswith("PROMPT_ID: agent_budget")]
    assert calls
    evidence = json.loads(calls[0]["user_prompt"])["grounding"]
    assert evidence["saved_budget_context"]["selected_budget"]["categories"] == {"food": 600}
    assert evidence["spending_context"]["category_totals"] == {"food": 200}


def test_ambiguous_scope_does_not_borrow_the_default_plan_or_spending():
    o = orchestrator()
    r = scope_budget_request(
        request(),
        RouterDecision(
            selected_agents=["budget"], rationale=["Unclear"], budget_scope_unclear=True
        ),
    )
    state = {"request": r, "sanitized_message": r.message}
    task = o._create_task(state, AgentName.BUDGET)
    assert "selected_budget" not in task.input_data["planning_context"]
    assert r.snapshot.recent_transactions == []
    assert (
        o.agents[AgentName.BUDGET]._preflight(task, task.sanitized_message).status == "needs_input"
    )
