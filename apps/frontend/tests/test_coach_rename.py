import httpx
import pytest
from streamlit.testing.v1 import AppTest
from test_app import CoachClient


def conversation_app(client=None):
    client = client or CoachClient()
    client.create_chat_session("coach-user", "Original title")
    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "coach-user"
    return app.run()


def submit(app, label):
    next(button for button in app.sidebar.button if button.label == label).click().run()


def test_inline_rename_save_cancel_and_reopen_use_persisted_title():
    app = conversation_app()
    app.sidebar.button(key="coach-rename-action-coach-session-1").click().run()
    assert not any(button.key == "coach-session-coach-session-1" for button in app.sidebar.button)
    app.sidebar.text_input[0].set_value("  New title  ")
    submit(app, "Save")
    assert app.sidebar.button(key="coach-session-coach-session-1").label == "New title"
    assert "coach_rename_open" not in app.session_state

    app.sidebar.button(key="coach-rename-action-coach-session-1").click().run()
    assert app.sidebar.text_input[0].value == "New title"
    app.sidebar.text_input[0].set_value("Discard this")
    submit(app, "Cancel")
    app.sidebar.button(key="coach-rename-action-coach-session-1").click().run()
    assert app.sidebar.text_input[0].value == "New title"
    assert not app.exception


@pytest.mark.parametrize("title", ["   ", "Unsaved title"])
def test_empty_or_failed_rename_keeps_editor_and_original_title(title):
    class FailingClient(CoachClient):
        def rename_chat_session(self, user_id, session_id, title):
            raise httpx.ConnectError("Service unavailable")

    app = conversation_app(FailingClient())
    app.sidebar.button(key="coach-rename-action-coach-session-1").click().run()
    app.sidebar.text_input[0].set_value(title)
    submit(app, "Save")
    assert not app.exception
    assert app.error
    assert app.session_state["coach_rename_open"] == "coach-session-1"
    assert app.sidebar.text_input[0].value == title
    assert app.session_state["backend_client"].sessions["coach-session-1"]["title"] == "Original title"
