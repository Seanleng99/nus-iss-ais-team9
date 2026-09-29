from streamlit.testing.v1 import AppTest


def test_cashflow_editor_requires_confirmation_and_is_opened_explicitly():
    app = AppTest.from_string("""
import streamlit as st
from ui.cashflow import render_cashflow
class Client:
    def get_cashflow_settings(self, user): return None
    def save_cashflow_settings(self, user, payload):
        st.session_state['saved_cashflow'] = payload
        return payload
render_cashflow(Client(), 'u')
""").run(timeout=30)
    assert not app.exception
    assert not app.date_input
    app.button[0].click().run()
    assert not app.exception
    next(item for item in app.button if item.label == "Save cash-flow settings").click().run()
    assert any("Supply and confirm" in item.value for item in app.warning)
