from datetime import date

from streamlit.testing.v1 import AppTest

TREND_INSIGHT = {
    "insight_id": "trend_transport_decreased",
    "insight_type": "trend",
    "title": "Transport spending decreased 100%",
    "description": (
        "Recorded transport expenses changed from SGD 876.50 to SGD 0.00 "
        "for the selected month."
    ),
    "category": "transport",
    "confidence": 0.25,
    "suggested_action": "Check whether the comparison includes the same period.",
}


def test_question_names_the_concrete_month():
    from ui.spending_insights_component.spending_insights import build_insight_coach_question

    question = build_insight_coach_question(
        TREND_INSIGHT, "October 2026", "How can I manage this trend?"
    )
    assert "October 2026" in question
    assert "Transport spending" in question
    assert question.endswith("How can I manage this trend?")


def test_question_without_category_still_names_the_month():
    from ui.spending_insights_component.spending_insights import build_insight_coach_question

    insight = {**TREND_INSIGHT, "category": None}
    question = build_insight_coach_question(insight, "October 2026", "Is this pattern normal?")
    assert "October 2026" in question
    assert "my spending for October 2026" in question


def insight_app():
    app = AppTest.from_string(
        "from ui.spending_insights_component.spending_insights import render_insight_card\n"
        f"render_insight_card({TREND_INSIGHT!r})"
    )
    app.session_state["active_period"] = date(2026, 10, 1)
    return app.run()


def test_coach_button_stores_question_with_explicit_month(monkeypatch):
    from ui.spending_insights_component import spending_insights

    sent: list[str] = []
    monkeypatch.setattr(
        spending_insights, "_navigate_to_coach_with_question", sent.append
    )
    app = insight_app()
    app.button(key="coach-prompt-trend_transport_decreased").click().run()
    assert not app.exception
    assert len(sent) == 1
    assert "October 2026" in sent[0]
    assert "Transport" in sent[0]
