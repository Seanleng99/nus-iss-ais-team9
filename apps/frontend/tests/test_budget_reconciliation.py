from streamlit.testing.v1 import AppTest


def test_matching_needs_all_fields_then_separate_confirmation():
    app = AppTest.from_string("""
import streamlit as st
from ui.budget_reconciliation import render_reconciliation
class Client:
    def get_budget_workspace(self, user):
        return {"settings": {"cashflow": {"schedules": [{"id":"bill", "name":"Rent", "kind":"expense"}]}},
                "reconciliation": {"links": [], "transactions": [{"id":"txn", "description":"Rent payment", "occurred_on":"2026-09-05", "type":"expense", "unallocated":600}]}}
    def preview_workspace_change(self, user, operation, payload):
        st.session_state['preview_calls'] = st.session_state.get('preview_calls', 0) + 1
        return {"preview_id":"p", "operation":operation, "details":{"transaction":"Rent payment", "bill":"Rent", "match":payload, "before":{"remaining":1500}, "after":{"remaining":900}}}
    def confirm_workspace_change(self, user, preview_id):
        st.session_state['confirmed_match'] = preview_id
        return {"saved":True}
render_reconciliation(Client(), 'u')
""").run(timeout=30)
    app.button[0].click().run()
    next(b for b in app.button if b.label == "Preview bill match").click().run()
    assert not app.exception
    assert any("Choose the record" in w.value for w in app.warning)
    assert "preview_calls" not in app.session_state
    app.selectbox[0].select_index(1)
    app.selectbox[1].select_index(1)
    app.date_input[0].set_value("2026-09-05")
    app.number_input[0].set_value(600.0)
    app.selectbox[2].select_index(1)
    next(b for b in app.button if b.label == "Preview bill match").click().run()
    assert not app.exception
    assert app.session_state["preview_calls"] == 1
    assert "confirmed_match" not in app.session_state
    assert app.metric[0].value == "SGD 900.00"
    next(b for b in app.button if b.label == "Confirm reviewed change").click().run()
    assert not app.exception
    assert app.session_state["confirmed_match"] == "p"


def test_refund_questions_only_appear_for_refunds_and_never_assume_the_effect():
    app = AppTest.from_string('''
import streamlit as st
from ui.budget_reconciliation import render_reconciliation
class Client:
    def get_budget_workspace(self, user):
        return {"settings": {"cashflow": {"schedules": [{"id":"bill", "name":"Rent", "kind":"expense"}]}},
            "reconciliation": {"links": [], "transactions": [
                {"id":"payment", "description":"Rent payment", "occurred_on":"2026-10-05", "type":"expense", "unallocated":600},
                {"id":"refund", "description":"Rent refund", "occurred_on":"2026-10-06", "type":"refund", "unallocated":50}]}}
    def preview_workspace_change(self, user, operation, payload):
        st.session_state["proposed_match"] = payload
        return {"preview_id":"p", "operation":operation, "details":{"transaction":"Rent refund", "bill":"Rent", "match":payload, "before":{"remaining":0}, "after":{"remaining":50}}}
render_reconciliation(Client(), 'u')
''').run(timeout=30)
    def control(items, label):
        return next(i for i in items if i.label == label)
    control(app.button, "Open bill matching").click().run()
    control(app.selectbox, "Recorded payment or refund").set_value("payment").run()
    assert not any(i.label == "Should this refund reduce recorded budget spending?" for i in app.selectbox)
    control(app.selectbox, "Recorded payment or refund").set_value("refund").run()
    assert control(app.selectbox, "After this refund, is the amount still payable?").value == "Choose"
    assert control(app.selectbox, "Should this refund reduce recorded budget spending?").value == "Choose"
    control(app.selectbox, "Bill").set_value("bill")
    app.date_input[0].set_value("2026-10-05")
    app.number_input[0].set_value(50)
    control(app.button, "Preview bill match").click().run()
    assert not app.exception
    assert "proposed_match" not in app.session_state
    control(app.selectbox, "After this refund, is the amount still payable?").set_value("Refund — amount becomes payable again")
    control(app.selectbox, "Should this refund reduce recorded budget spending?").set_value("Reduce spending in the refund month")
    control(app.button, "Preview bill match").click().run()
    assert not app.exception
    assert app.session_state["proposed_match"]["effect"] == "refund_reopens"
    assert app.session_state["proposed_match"]["spending_treatment"] == "reduce_expense"
