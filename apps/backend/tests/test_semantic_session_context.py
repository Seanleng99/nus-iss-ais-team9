"""Owned excerpts, corrected values and typed clarification metadata."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.api.financial_schemas import TransactionCreate
from app.domain.schemas import AgentResult, CoachResponse
from app.infrastructure.models import PlanningPreferencesRecord, UserRecord
from app.infrastructure.repositories import SQLAlchemyTransactionRepository
from app.services.budget_planning import build_planning_context
from app.services.conversation_summary import roll_summary
from app.services.session_context import complete_state, empty_state


def observation(message, **kwargs):
    return {"kind": "fact", "field": "monthly_income", "value": "4800", "source_quote": message,
            "source_position": 7, "attribution": "self", "cadence": "monthly", "topics": ["budget"], **kwargs}


def response(message, observations=None, **turn):
    return CoachResponse(session_id="chat", selected_agents=["budget"], answer=message,
                         agent_results=[], disclaimers=[], audit={"turn_decision": {
                             "session_observations": observations or [], "missing_fields": [], **turn}})


def test_numbered_aliases_collapse_without_merging_conflicting_topics():
    message = "Compare mutual funds and ETFs."
    def referent(subject, topic):
        return {"subject": subject, "agent": "investment_education", "education_topics": [topic],
                "source_quote": message, "source_position": 1, "option_index": 1}
    state = empty_state()
    state["referents"] = [referent("mutual funds", "mutual funds")]
    current = complete_state(state, response("Funds and ETFs", referents=[
        referent("funds", "mutual funds")]), message, 1)
    assert len(current["referents"]) == 1
    assert current["referents"][0]["subject"] == "funds"
    conflicting = complete_state(current, response("ETFs", referents=[
        referent("ETFs", "exchange-traded funds")]), message, 1)
    assert len(conflicting["referents"]) == 2


def test_unfamiliar_self_statement_retains_exact_value_and_attribution():
    message = "The amount landing in my account each month is SGD 4.8k."
    state = complete_state(empty_state(), response(message, [observation(message)]), message, 7)
    assert state["facts"]["monthly_income"] == {"value": "4800", "source_position": 7, "status": "user_reported"}
    assert state["observations"][0]["source_quote"] == message


@pytest.mark.parametrize("suffix", [
    "What if rent were higher?", 'Could you explain the "savings first" method?',
    "My spouse uses another method.",
])
def test_unrelated_hypothetical_quote_or_third_party_clause_does_not_erase_self_fact(suffix):
    quote = "The amount landing in my account each month is SGD 4800."
    message = quote + " " + suffix
    state = complete_state(empty_state(), response(message, [observation(quote)]), message, 7)
    assert state["facts"]["monthly_income"]["value"] == "4800"


@pytest.mark.parametrize("prefix,suffix", [("If ", ", would that work?"),
                                           ('The example says "', '".'),
                                           ("My spouse said: ", ".")])
def test_extracted_self_quote_keeps_its_enclosing_hypothetical_or_other_speaker(prefix, suffix):
    quote = "I receive SGD 4800 each month"
    message = prefix + quote + suffix
    state = complete_state(empty_state(), response(message, [observation(quote)]), message, 7)
    assert not state["facts"]


@pytest.mark.parametrize("message,changes", [
    ("If SGD 4800 lands in my account each month, what happens?", {}),
    ('The example says "I receive SGD 4800 each month".', {}),
    ("My spouse gets SGD 4800 each month.", {}),
    ("I receive SGD 4800 each week.", {}),
    ("I receive USD 4800 each month.", {}),
    ("I receive SGD -4800 each month.", {}),
    ("The example says 'I receive SGD 4800 each month'.", {}),
    ("I receive SGD 4800 each month.", {"value": "5800"}),
    ("I receive SGD 4800 each month.", {"source_position": 5}),
    ("I receive SGD 4800 each month.", {"source_quote": "I receive SGD 4800 yearly."}),
    ("I receive SGD 4800 each month.", {"attribution": "other"}),
])
def test_model_metadata_cannot_promote_unreported_or_invented_values(message, changes):
    state = complete_state(empty_state(), response(message, [observation(message, **changes)]), message, 7)
    assert not state["facts"]
    assert not state["observations"]


def test_correction_supersedes_exact_owned_source_without_authorizing_a_write():
    old = empty_state()
    old["facts"]["monthly_income"] = {"value": "5000", "source_position": 1, "status": "user_reported"}
    message = "Actually the amount reaching me each month is SGD 4800."
    state = complete_state(old, response(message, [observation(message)]), message, 7)
    assert state["facts"]["monthly_income"]["supersedes_position"] == 1
    assert "confirmed" not in state and "confirmed" not in state["facts"]["monthly_income"]
    assert old["facts"]["monthly_income"]["value"] == "5000"


def test_new_missing_fields_ignore_question_language_and_legacy_regex():
    resp = response("Could you clarify?", missing_fields=["goal_target_months"])
    resp.agent_results = [AgentResult(agent="budget", summary="Clarify", rationale=[], confidence=1,
                                    data={"questions": ["What is your monthly income?"]})]
    state = complete_state(empty_state(), resp, "Help me plan.", 7)
    assert state["pending_fields"] == ["goal_target_months"]


def test_semantic_preference_survives_older_summary_without_preference_trigger_words():
    message = "Dense paragraphs make this hard to read; one idea at a time works for me."
    metadata = observation(message, kind="preference", field=None, value=None, cadence="unknown")
    state = complete_state(empty_state(), response(message, [metadata]), message, 7)
    messages = [SimpleNamespace(position=7, role="user", content=message),
                SimpleNamespace(position=8, role="assistant", content="A clear explanation.",
                                orchestration_trace=SimpleNamespace(blocked=False))]
    summary = roll_summary(None, messages, 17, {}, state["observations"])
    assert summary["notes"][0]["kind"] == "preference"
    assert summary["notes"][0]["topics"] == ["budget"]
    assert summary["notes"][0]["user_excerpt"] == message


def test_blocked_response_and_unknown_position_never_persist_model_observations():
    message = "I receive SGD 4800 each month."
    resp = response(message, [observation(message)])
    resp.blocked = True
    assert complete_state(empty_state(), resp, message, 7) is None
    resp.blocked = False
    assert not complete_state(empty_state(), resp)["facts"]


def test_referents_require_exact_current_source_and_reviewed_subject():
    message = "Compare two approaches."
    subject = {"subject": "bonds", "agent": "investment_education", "education_topics": ["bonds"],
               "source_quote": message, "source_position": 7, "option_index": 1}
    resp = response("One approach uses bonds.", referents=[subject, {**subject, "source_position": 3},
                                                          {**subject, "subject": "unmentioned"}])
    state = complete_state(empty_state(), resp, message, 7)
    assert state["referents"] == [subject]


def test_successful_prose_rewrite_invalidates_old_order_but_preserves_background_subjects():
    previous = empty_state()
    previous["referents"] = [
        {"subject": "bonds", "agent": "investment_education", "education_topics": ["bonds"],
         "source_quote": "Compare approaches.", "source_position": 1, "option_index": 1},
        {"subject": "budget", "agent": "budget", "education_topics": [],
         "source_quote": "Explain budgets.", "source_position": 3},
    ]
    resp = response("A concise revised explanation.")
    resp.audit["presentation_rewritten"] = True
    state = complete_state(previous, resp, "Please make this concise.", 7)
    assert [item["subject"] for item in state["referents"]] == ["budget"]
    assert previous["referents"][0]["option_index"] == 1


def test_successful_rewrite_retains_only_new_displayed_order_with_owned_provenance():
    previous = empty_state()
    previous["referents"] = [{"subject": "bonds", "agent": "investment_education",
                              "education_topics": ["bonds"], "source_quote": "Compare approaches.",
                              "source_position": 1, "option_index": 1}]
    message = "Reverse the two educational options."
    new = [{"subject": topic, "agent": "investment_education", "education_topics": [topic],
            "source_quote": message, "source_position": 7, "option_index": index}
           for index, topic in enumerate(("exchange-traded funds", "bonds"), 1)]
    resp = response("First: exchange-traded funds. Second: bonds.", referents=new)
    resp.audit["presentation_rewritten"] = True
    state = complete_state(previous, resp, message, 7)
    assert state["referents"] == new


def test_blocked_or_unrewritten_response_cannot_invalidate_existing_option_order():
    previous = empty_state()
    previous["referents"] = [{"subject": "bonds", "agent": "investment_education",
                              "education_topics": ["bonds"], "source_quote": "Compare approaches.",
                              "source_position": 1, "option_index": 1}]
    resp = response("The current options stay available.")
    resp.audit["presentation_rewritten"] = False
    assert complete_state(previous, resp, "Explain this.", 7)["referents"] == previous["referents"]
    resp.audit["presentation_rewritten"] = True
    resp.blocked = True
    assert complete_state(previous, resp, "Explain this.", 7) is None
    assert previous["referents"][0]["option_index"] == 1


def test_planning_evidence_survives_paraphrases_without_trigger_nouns(db_session_factory):
    with db_session_factory() as db:
        db.add(UserRecord(id="evidence-user"))
        db.flush()
        db.add(PlanningPreferencesRecord(user_id="evidence-user", data={
            "cashflow": {"opening_balance": 900, "schedules": []},
            "reserves": {"funds": [{"name": "School fees", "amount": 120}]},
            "review_preferences": {"frequency": "monthly"},
            "constraints:2026-10-01": {"policy": {"protected_categories": ["housing"]}},
            "timing:2026-10-01": {"review_day": 15},
        }))
        SQLAlchemyTransactionRepository(db).create("evidence-user", TransactionCreate(
            description="Groceries", category="food", amount={"amount": 100}, occurred_on="2026-09-09"))
        context = build_planning_context(db, "evidence-user", today=date(2026, 10, 1),
                                         message="Make the money arrive before the roof payment.")
        settings = context["workspace"]["settings"]
        assert {"cashflow", "reserves", "review_preferences", "constraints:2026-10-01", "timing:2026-10-01"} <= settings.keys()
        assert context["recorded_spending"][0]["categories"] == {"food": 100.0}
        assert context["request_scope"]["selection"] == "semantic"
        assert len(context["request_scope"]["operations"]) == 12
        assert "budgets" in context["request_scope"]["operations"]


def test_planning_limits_are_reported_and_requested_period_is_retained(db_session_factory):
    with db_session_factory() as db:
        db.add(UserRecord(id="bounded-user"))
        db.flush()
        data = {f"constraints:{year}-01-01": {"policy": {"note": "bounded"}}
                for year in range(2020, 2050)}
        data["cashflow"] = {"schedules": [{"name": "x" * 300}] * 110}
        db.add(PlanningPreferencesRecord(user_id="bounded-user", data=data))
        context = build_planning_context(db, "bounded-user", today=date(2026, 10, 1),
                                         message="Keep this workable.", period=date(2020, 1, 1))["workspace"]
        assert "constraints:2020-01-01" in context["settings"]
        assert len(context["settings"]["cashflow"]["schedules"]) == 100
        assert context["context_bounds"]["truncated"]
        assert context["context_bounds"]["dated_settings_total"] == 30
        assert context["context_bounds"]["dated_settings_included"] == 16
