from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_budget_planning import PERIOD, confirm, planning_draft, stage

from app.api.financial_schemas import BudgetUpsert
from app.core.config import settings
from app.infrastructure.repositories import SQLAlchemyBudgetRepository, SQLAlchemyChatRepository
from app.main import app
from app.services.budget_capture import BudgetDraft
from app.services.budget_methods import method_report
from app.services.budget_planning import PlanningInputs
from app.services.budget_scenarios import compare_draft


def draft(method=None, **updates):
    data = planning_draft(
        categories=[
            {"category": "housing", "limit_amount": 2000},
            {"category": "hobbies", "limit_amount": 1000},
        ]
    )
    data["planning"]["method"] = method or {"name": "flexible"}
    data.update(updates)
    return data


def test_percentage_targets_use_full_take_home_and_do_not_change_amounts():
    inputs = PlanningInputs.model_validate(
        draft({"name": "50_30_20", "category_groups": {"housing": "needs", "hobbies": "wants"}})[
            "planning"
        ]
    )
    original = inputs.model_dump()
    report = method_report({"housing": 2100, "hobbies": 1000}, inputs)
    assert report["targets"] == {"needs": 2000, "wants": 1200, "savings": 800}
    assert report["actual"] == {"needs": 2100, "wants": 1000, "savings": 800}
    assert "guidance" in report["warnings"][0]
    assert inputs.model_dump() == original


@pytest.mark.parametrize(
    "method",
    [
        {"name": "50_30_20"},
        {"name": "custom"},
        {"name": "custom", "percentages": {"needs": 60, "wants": 30, "savings": 20}},
        {"name": "80_20", "percentages": {"needs": 50, "wants": 30, "savings": 20}},
        {"name": "zero_based"},
    ],
)
def test_incomplete_or_inconsistent_method_cannot_be_saved(method):
    with pytest.raises(ValidationError):
        BudgetUpsert.model_validate(draft(method))


def test_zero_based_requires_allocation_but_never_fills_the_gap():
    inputs = PlanningInputs.model_validate(draft({"name": "zero_based"})["planning"])
    assert method_report({"housing": 3000}, inputs)["questions"]
    assert inputs.savings_target == 800
    assert not method_report({"housing": 3200}, inputs)["questions"]


def test_custom_targets_round_to_exact_income_even_for_small_amounts():
    inputs = PlanningInputs(
        take_home_income=0.01,
        income_basis="take_home",
        savings_target=0,
        method={"name": "custom", "percentages": {"needs": 50, "wants": 50, "savings": 0}},
    )
    report = method_report({}, inputs)
    assert sum(report["targets"].values()) == 0.01
    assert min(report["targets"].values()) >= 0


def test_80_20_and_savings_first_keep_user_savings_choice():
    inputs = PlanningInputs(
        take_home_income=4000,
        income_basis="take_home",
        savings_target=500,
        method={"name": "80_20"},
    )
    assert method_report({"housing": 3000}, inputs)["targets"] == {"expenses": 3200, "savings": 800}
    assert inputs.savings_target == 500
    inputs.method.name = "pay_yourself_first"
    assert method_report({"housing": 3000}, inputs)["targets"] == {"expenses": 3500, "savings": 500}


def test_scenarios_are_independent_preserve_categories_and_accept_explicit_zero():
    original = BudgetDraft.model_validate(
        draft(
            action="compare",
            scenarios=[
                {"name": "Less income", "take_home_income": 3000},
                {"name": "No hobbies", "categories": [{"category": "hobbies", "limit_amount": 0}]},
                {"name": "More saving", "savings_target": 1500},
            ],
        )
    )
    before = original.model_dump()
    report = compare_draft(original, {"insurance": 100})
    assert original.model_dump() == before
    assert [item["totals"]["funding_gap"] for item in report["results"]] == [0, 900, 0, 600]
    assert report["results"][2]["totals"]["unallocated"] == 1100
    assert report["results"][2]["unallocated_change"] == 1000
    assert not report["saved"]


@pytest.mark.parametrize(
    "scenarios",
    [
        [{"name": "A"}, {"name": "a"}],
        [{"name": "Current plan"}],
    ],
)
def test_ambiguous_scenario_names_require_clarification(scenarios):
    report = compare_draft(BudgetDraft.model_validate(draft(action="compare", scenarios=scenarios)))
    assert report["questions"] and not report["results"]


def test_duplicate_category_overrides_are_not_silently_accepted():
    report = compare_draft(
        BudgetDraft.model_validate(
            draft(
                action="compare",
                scenarios=[
                    {
                        "name": "Alternative",
                        "categories": [
                            {"category": "housing", "limit_amount": 10},
                            {"category": "Housing", "limit_amount": 20},
                        ],
                    },
                ],
            )
        )
    )
    assert any("duplicate" in question for question in report["results"][1]["questions"])


def test_comparison_adoption_requires_actual_income_coverage_and_final_confirmation(
    db_session_factory,
):
    with db_session_factory() as session:
        response = stage(
            session,
            draft(action="compare", scenarios=[{"name": "Option A", "savings_target": 1000}]),
        )
        assert "nothing has been saved" in response.answer
        assert "comparison cannot be saved" in confirm(session).answer
        # An AI response cannot silently select a scenario.
        assert "Choose a stored scenario" in stage(session, draft()).answer
        assert SQLAlchemyBudgetRepository(session).get("u1", PERIOD) is None
        assert "unsaved draft" in confirm(session, "use scenario Option A").answer
        assert "take-home" in confirm(session).answer
        pending = deepcopy(
            SQLAlchemyChatRepository(session).get("u1", "plan").pending_budget["draft"]
        )
        assert pending["planning"]["income_basis"] == "unknown"
        assert pending["planning"]["expenses_confirmed"] is False
        pending["planning"].update(income_basis="take_home", expenses_confirmed=True)
        assert "confirm budget" in stage(session, pending).answer
        assert confirm(session).answer.startswith("Saved")
        record = SQLAlchemyBudgetRepository(session).get("u1", PERIOD)
        assert record.planning["savings_target"] == 1000
        assert record.planning["method"]["name"] == "flexible"


def test_stale_and_expired_comparisons_cannot_be_adopted(db_session_factory):
    with db_session_factory() as session:
        stage(session, draft(action="compare", scenarios=[{"name": "Alternative"}]))
        SQLAlchemyBudgetRepository(session).upsert("u1", BudgetUpsert.model_validate(draft()))
        assert "budget changed" in confirm(session, "use scenario Alternative").answer
        stage(session, draft(action="compare", scenarios=[{"name": "Alternative"}]))
        chat = SQLAlchemyChatRepository(session).get("u1", "plan")
        chat.pending_budget = {
            **chat.pending_budget,
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        }
        assert "expired" in confirm(session, "use scenario Alternative").answer


def test_compare_endpoint_is_read_only_and_validates_input():
    client = TestClient(app)
    headers = {"X-API-Key": settings.api_key}
    payload = draft(
        action="compare", scenarios=[{"name": "Reduced income", "take_home_income": 2000}]
    )
    result = client.post("/api/users/u1/budget/compare", headers=headers, json=payload)
    assert result.status_code == 200
    assert result.json()["results"][1]["totals"]["funding_gap"] == 1800
    assert (
        client.get("/api/users/u1/budget?period_start=2026-10-01", headers=headers).status_code
        == 404
    )
    payload["scenarios"][0]["take_home_income"] = -1
    assert (
        client.post("/api/users/u1/budget/compare", headers=headers, json=payload).status_code
        == 422
    )
    assert client.post("/api/users/u1/budget/compare", json=draft()).status_code in (401, 403)


def test_v1_plan_settings_remain_readable():
    payload = draft()
    payload["planning"].pop("method")
    payload["planning"]["version"] = "budget-planning-v1"
    parsed = BudgetUpsert.model_validate(payload)
    assert parsed.planning.method.name == "flexible"


def test_method_survives_save_readback_and_owner_scope_is_enforced(monkeypatch):
    from test_security import StubTokenVerifier

    from app.core import security

    monkeypatch.setattr(settings, "oidc_auth_enabled", True)
    monkeypatch.setattr(security, "get_oidc_token_verifier", StubTokenVerifier)
    client = TestClient(app)
    alice = {"Authorization": "Bearer alice-token"}
    bob = {"Authorization": "Bearer bob-token"}
    assert (
        client.post("/api/profiles", headers=alice, json={"user_id": "alice-plan"}).status_code
        == 201
    )
    method = {"name": "50_30_20", "category_groups": {"housing": "needs", "hobbies": "wants"}}
    saved = client.put("/api/users/alice-plan/budget", headers=alice, json=draft(method))
    assert saved.status_code == 200
    assert saved.json()["planning"]["method"] == {**method, "percentages": None}
    read = client.get("/api/users/alice-plan/budget?period_start=2026-10-01", headers=alice)
    assert read.json()["planning"]["method"] == saved.json()["planning"]["method"]
    denied = client.post("/api/users/alice-plan/budget/compare", headers=bob, json=draft(method))
    assert denied.status_code == 404


def test_non_sgd_comparison_does_not_label_foreign_amounts_as_sgd():
    result = compare_draft(BudgetDraft.model_validate(draft(currency="USD")))
    assert result["results"][0]["totals"] is None
    assert result["results"][0]["method"] is None
    assert any("currency" in question for question in result["results"][0]["questions"])
