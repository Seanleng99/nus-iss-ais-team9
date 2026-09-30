import pytest
from test_budget_workspace import change, confirm, setup, stage, txn

from app.infrastructure.repositories import SQLAlchemyChatRepository
from app.services.budget_edits import apply_edits
from app.services.budget_workspace import confirm_change, preview_change
from app.services.financial_workspace import read_section


def edit(amount):
    return {"edits": [{"collection": "schedules", "action": "update", "key": "rent", "values": {"amount": amount}}]}


def test_coach_edit_clarify_correct_confirm_cancel_stale(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        chat = SQLAlchemyChatRepository(session).create("u", "chat", "Budget")
        stage(session, chat, "cashflow", edit(1600), questions=["Which rent amount?"])
        assert not chat.pending_budget["ready"]
        assert "missing" in confirm(session).answer
        stage(session, chat, "cashflow", edit(1700))
        assert chat.pending_budget["workspace_preview"]["target"]["schedules"][0]["name"] == "Rent"
        assert read_section(session, "u", "cashflow")["schedules"][0]["amount"] == 1500
        stage(session, chat, "cashflow", edit(1800))
        assert "Saved" in confirm(session).answer
        assert read_section(session, "u", "cashflow")["schedules"][0]["amount"] == 1800
        stage(session, chat, "cashflow", edit(1900))
        assert "cancelled" in confirm(session, "cancel").answer
        stage(session, chat, "cashflow", edit(2000))
        txn(session)
        assert "changed" in confirm(session).answer
        assert read_section(session, "u", "cashflow")["schedules"][0]["amount"] == 1800


def test_add_remove_preserves_unrelated_and_rejects_missing_selector(db_session_factory):
    with db_session_factory() as session:
        setup(session)
        preview = preview_change(session, "u", change("cashflow", {"edits": [{"collection": "schedules", "action": "add", "values": {"name": "Payday", "category": "salary", "kind": "income", "amount": 5000, "first_on": "2026-09-25", "frequency": "monthly"}}]}))
        assert len(preview["target"]["schedules"]) == 2
        confirm_change(session, "u", preview)
        proposed = preview_change(session, "u", change("cashflow", edit(1700)))["target"]
        assert proposed["schedules"][1]["amount"] == 5000
        proposed = preview_change(session, "u", change("cashflow", {"edits": [{"collection": "schedules", "action": "remove", "key": "rent"}]}))["target"]
        assert len(proposed["schedules"]) == 1 and proposed["schedules"][0]["name"] == "Payday"
        with pytest.raises(ValueError, match="missing or ambiguous"):
            preview_change(session, "other", change("cashflow", edit(1700)))


def test_collection_edit_ambiguity_and_replacement_conflicts():
    policy = {"debts": [{"name": "Loan", "balance": 100}, {"name": "Loan", "balance": 200}], "protected_categories": ["housing"], "category_floors": {"food": 100}}
    with pytest.raises(ValueError, match="ambiguous"):
        apply_edits("commitments", policy, {"edits": [{"collection": "debts", "action": "update", "key": "Loan", "values": {"balance": 50}}]})
    result = apply_edits("commitments", policy, {"edits": [{"collection": "protected_categories", "action": "add", "key": "Food"}, {"collection": "category_floors", "action": "update", "key": "food", "values": {"amount": 200}}]})
    assert result["protected_categories"] == ["housing", "food"] and result["category_floors"] == {"food": 200}
    assert policy["category_floors"] == {"food": 100}
    with pytest.raises(ValueError, match="either edits"):
        apply_edits("cashflow", {}, {"schedules": [], **edit(100)})
