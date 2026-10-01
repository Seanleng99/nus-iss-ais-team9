import json
from datetime import date

from app.api.financial_schemas import BudgetUpsert
from app.domain.schemas import CoachRequest, CoachResponse
from app.infrastructure.repositories import SQLAlchemyBudgetRepository, SQLAlchemyChatRepository
from app.services.budget_capture import handle_budget_confirmation, stage_budget_draft
from app.services.budget_constraints import (
    AllocationPolicy,
    AlternativesRequest,
    build_alternatives,
    requirements,
    save_policy,
)
from app.services.budget_planning import build_planning_context
from app.services.budget_workspace import WorkspaceChange, confirm_change, preview_change
from app.services.financial_workspace import read_section, write_section

PERIOD = date(2026, 10, 1)


def seed(session, user="u"):
    return SQLAlchemyBudgetRepository(session).upsert(
        user,
        BudgetUpsert(
            period_start=PERIOD,
            categories=[
                {"category": "housing", "limit_amount": 1500},
                {"category": "food", "limit_amount": 500},
            ],
            planning={"take_home_income": 3000, "savings_target": 800},
        ),
    )


def test_single_fixed_category_needs_no_optimizer_policy_and_preserves_other_settings(
    db_session_factory,
):
    with db_session_factory() as session:
        seed(session)
        save_policy(
            session,
            "u",
            AllocationPolicy(period_start=PERIOD, confirmed=True, category_floors={"food": 400}),
        )
        pending = preview_change(
            session,
            "u",
            WorkspaceChange(
                operation="commitments",
                payload_json=json.dumps(
                    {"period_start": str(PERIOD), "protected_categories": ["housing"]}
                ),
            ),
        )
        assert pending["target"]["minimum_savings"] is None
        assert pending["target"]["max_reduction_percent"] is None
        assert requirements(session, "u", PERIOD)["floors"] == {"food": 40000}
        confirm_change(session, "u", pending)
        assert requirements(session, "u", PERIOD)["floors"] == {"food": 40000, "housing": 150000}
        stored = read_section(session, "u", "constraints:" + str(PERIOD))["policy"]
        assert stored["category_floors"] == {"food": 400}


def test_more_savings_can_be_compared_without_commitments_and_without_choosing_cuts(
    db_session_factory,
):
    with db_session_factory() as session:
        seed(session)
        result = build_alternatives(
            session, "u", AlternativesRequest(period_start=PERIOD, savings_target=1100)
        )
        assert len(result["results"]) == 2
        assert result["results"][1]["totals"]["funding_gap"] == 100
        assert result["results"][1]["draft"]["planning"]["savings_target"] == 1100
        assert {
            c["category"]: c["limit_amount"] for c in result["results"][1]["draft"]["categories"]
        } == {"housing": 1500, "food": 500}
        assert "Which category" in " ".join(result["questions"])
        assert (
            SQLAlchemyBudgetRepository(session).get("u", PERIOD).planning["savings_target"] == 800
        )
        assert not build_alternatives(session, "other", AlternativesRequest(period_start=PERIOD))[
            "results"
        ]


def test_partial_policy_does_not_invent_savings_or_allow_automatic_reductions(db_session_factory):
    with db_session_factory() as session:
        seed(session)
        save_policy(
            session,
            "u",
            AllocationPolicy(period_start=PERIOD, confirmed=True, protected_categories=["housing"]),
        )
        result = build_alternatives(
            session, "u", AlternativesRequest(period_start=PERIOD, savings_target=100)
        )
        assert result["results"][1]["draft"]["planning"]["savings_target"] == 100
        assert requirements(session, "u", PERIOD)["savings"] == 0
        assert requirements(session, "u", PERIOD)["floors"] == {"housing": 150000}


def test_editing_an_unrelated_policy_field_preserves_the_reduction_reference(db_session_factory):
    with db_session_factory() as session:
        seed(session)
        save_policy(
            session,
            "u",
            AllocationPolicy(period_start=PERIOD, confirmed=True, max_reduction_percent=50),
        )
        repository = SQLAlchemyBudgetRepository(session)
        repository.upsert(
            "u",
            BudgetUpsert(
                period_start=PERIOD,
                categories=[
                    {"category": "housing", "limit_amount": 1000},
                    {"category": "food", "limit_amount": 500},
                ],
                planning={"take_home_income": 3000, "savings_target": 800},
            ),
        )
        pending = preview_change(
            session,
            "u",
            WorkspaceChange(
                operation="commitments",
                payload_json=json.dumps(
                    {"period_start": str(PERIOD), "category_floors": {"food": 400}}
                ),
            ),
        )
        confirm_change(session, "u", pending)
        assert requirements(session, "u", PERIOD)["floors"]["housing"] == 75000
        assert (
            read_section(session, "u", "constraints:" + str(PERIOD))["reference_limits"]["housing"]
            == 1500
        )


def test_comparison_reuses_owned_saved_plan_but_adoption_and_save_remain_separate(
    db_session_factory,
):
    with db_session_factory() as session:
        seed(session)
        chat = SQLAlchemyChatRepository(session).create("u", "s", "Budget")
        response = CoachResponse(
            session_id="s",
            answer="draft",
            selected_agents=["budget"],
            disclaimers=[],
            audit={},
            agent_results=[
                {
                    "agent": "budget",
                    "summary": "draft",
                    "data": {
                        "budget_draft": {
                            "action": "compare",
                            "period_start": str(PERIOD),
                            "scenarios": [{"name": "Proposed change", "savings_target": 900}],
                        }
                    },
                }
            ],
        )
        stage_budget_draft(session, "u", chat, response)
        assert "SGD 100.00 unallocated" in response.answer
        assert "use this change" in response.answer
        assert not chat.pending_budget["ready"]
        assert "all your expenses" not in response.answer
        session.commit()
        adopted = handle_budget_confirmation(
            session, CoachRequest(user_id="u", session_id="s", message="use this change")
        )
        assert "unsaved draft" in adopted.answer
        assert not chat.pending_budget["ready"]
        assert chat.pending_budget["draft"]["planning"]["income_basis"] == "unknown"
        assert (
            SQLAlchemyBudgetRepository(session).get("u", PERIOD).planning["savings_target"] == 800
        )
        refused = handle_budget_confirmation(
            session, CoachRequest(user_id="u", session_id="s", message="confirm budget")
        )
        assert "take-home" in refused.answer
        assert (
            SQLAlchemyBudgetRepository(session).get("u", PERIOD).planning["savings_target"] == 800
        )


def test_ambiguous_simple_adoption_never_selects_an_option(db_session_factory):
    with db_session_factory() as session:
        chat = SQLAlchemyChatRepository(session).create("u", "s", "Budget")
        chat.pending_budget = {
            "comparison": {"results": [{"name": "Current plan"}, {"name": "One"}, {"name": "Two"}]}
        }
        response = handle_budget_confirmation(
            session, CoachRequest(user_id="u", session_id="s", message="use this change")
        )
        assert "Choose which option" in response.answer
        assert len(chat.pending_budget["comparison"]["results"]) == 3


def test_core_context_omits_unrelated_records_and_shares_verified_totals(db_session_factory):
    with db_session_factory() as session:
        seed(session)
        seed(session, "other")
        write_section(
            session,
            "u",
            "history:" + str(PERIOD),
            [{"id": "version", "saved_at": "2026-10-01", "reason": "edited"}],
        )
        context = build_planning_context(
            session, "u", message="What if I save more?", period=PERIOD
        )
        assert context["request_scope"] == {"operations": []}
        assert "reconciliation" not in context["workspace"]
        assert "budget_history" not in context["workspace"]
        assert "recorded_spending" not in context
        assert context["selected_period"] == str(PERIOD)
        assert context["selected_budget"]["affordability"]["unallocated"] == 200
        assert "selected_budget" not in build_planning_context(
            session, "missing", message="What if I save more?", period=PERIOD
        )


def test_pending_workspace_followup_keeps_relevant_context_without_all_records(db_session_factory):
    with db_session_factory() as session:
        context = build_planning_context(
            session,
            "u",
            message="Actually SGD 1200",
            pending={
                "action": "workspace",
                "workspace": {"operation": "cashflow"},
                "planning": None,
            },
        )
        assert context["request_scope"]["operations"] == ["cashflow"]
        assert "reconciliation" not in context["workspace"]
        matching = build_planning_context(
            session, "u", message="Match my recorded payment to the bill"
        )
        assert "reconciliation" in matching["workspace"]
