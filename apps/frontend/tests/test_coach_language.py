from pathlib import Path

import pytest
from language_fixtures import language_case
from streamlit.testing.v1 import AppTest
from test_app import CoachClient, FakeBackendClient, SparseProfileClient, WorkspaceDefaultsClient

SELECTOR = (
    "from ui.coach_language import current_selection, language_selector\n"
    "selection = current_selection('synthetic-language')\n"
    "language_selector('synthetic-language', selection or 'en')\n"
)


def test_explicit_selection_survives_a_new_session_from_the_same_url():
    app = AppTest.from_string(SELECTOR).run()
    app.selectbox[0].set_value("zh-Hans").run()
    assert not app.exception
    assert app.query_params["coach_language"] == ["zh-Hans"]
    reloaded = AppTest.from_string(SELECTOR)
    reloaded.query_params.update(app.query_params)
    reloaded.run()
    assert not reloaded.exception
    assert reloaded.selectbox[0].value == "zh-Hans"
    reloaded.selectbox[0].set_value("en").run()
    assert reloaded.query_params["coach_language"] == ["en"]
    assert reloaded.selectbox[0].options == ["English", "Chinese (Simplified)"]


def test_invalid_url_locale_falls_back_to_english():
    app = AppTest.from_string(SELECTOR)
    app.query_params["coach_language"] = "untrusted-invalid-locale"
    app.run()
    assert not app.exception
    assert app.selectbox[0].value == "en"


def test_chinese_coach_controls_and_starter_request_use_the_selected_locale():
    class RecordingClient(CoachClient):
        def ask_coach(self, payload):
            self.payload = payload
            result = super().ask_coach(payload)
            session = self.sessions[payload["session_id"]]
            session["messages"][-1]["explanation"]["trace_id"] = f"trace-fixture-{len(session['messages'])}"
            return result

    client = RecordingClient()
    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "synthetic-language"
    app.query_params["coach_language"] = "zh-Hans"
    app.run()
    assert not app.exception
    assert language_case("coach.title") in app.markdown[0].value
    assert app.chat_input[0].placeholder == language_case("coach.input")
    assert app.button(key="coach-starter-0").label == language_case("coach.starter")
    app.button(key="coach-starter-0").click().run()
    assert not app.exception
    assert client.payload["response_locale"] == "zh-Hans"
    assert client.payload["message"] == language_case("coach.starter")


def test_answer_metadata_labels_follow_ui_selection_without_rewriting_saved_answer():
    app = AppTest.from_string(
        "from ui.pages import _render_coach_message\n"
        "_render_coach_message({'role': 'assistant', 'content': 'Reviewed answer.', "
        "'explanation': {'response_locale': 'zh-Hans', 'response_language': 'English', "
        "'selected_agents': ['budget'], 'agent_results': [{'agent': 'budget', "
        "'confidence': 0.76, 'rationale': ['MISSING_REQUIRED_INPUT']}]}, "
        "'sources': [{'source_id': 'summary', 'title': 'Original source title', "
        "'issuing_organization': 'MoneySense', 'published_at': '2026-10-03', "
        "'canonical_url': 'https://example.com/source', 'document_filename': 'source.md', "
        "'content_kind': 'project_summary'}]}, 'en')"
    ).run()
    assert not app.exception
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Budget planning" in rendered and "Moderate confidence" in rendered
    assert "Project-written summary" in rendered
    assert "Source ID: summary" in rendered
    assert "RAG knowledge base references — no live web search" in [item.value for item in app.caption]
    assert "Why this answer and how certain it is" in [item.label for item in app.expander]
    assert "Reviewed answer." in rendered
    assert "[Original source title](https://example.com/source)" in rendered
    assert "source.md" in rendered


def test_profile_preference_sets_default_ui_without_explicit_language_setting():
    class ChineseProfileClient(CoachClient):
        def get_profile(self, user_id):
            return {"preferred_language": "Mandarin"}

    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = ChineseProfileClient()
    app.session_state["active_user_id"] = "synthetic-language"
    app.run()
    assert not app.exception
    assert language_case("coach.title") in app.markdown[0].value
    assert app.session_state["workspace-language"] == "zh-Hans"
    assert not app.selectbox
    assert "coach_language" not in app.query_params


def test_shared_header_restores_selection_after_page_navigation_clears_url():
    app = AppTest.from_string(
        "from ui.coach_language import render_language_header\n"
        "render_language_header('synthetic-language')\n"
    ).run()
    app.selectbox[0].set_value("zh-Hans").run()
    assert not app.exception
    app.query_params.clear()
    app.run()
    assert not app.exception
    assert app.selectbox[0].value == "zh-Hans"
    assert app.query_params["coach_language"] == ["zh-Hans"]


def test_language_is_shared_across_profiles_and_sidebar_navigation():
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py")
    app.session_state["backend_client"] = FakeBackendClient()
    app.run()
    app.main.selectbox[0].set_value("zh-Hans").run()
    assert not app.exception
    links = {item.label for item in app.sidebar.get("page_link")}
    assert {language_case("ui.overview"), language_case("ui.transactions"),
            language_case("ui.budget"), language_case("ui.goals")} <= links
    assert app.sidebar.selectbox[0].label == language_case("ui.active_profile")
    assert language_case("ui.currency") in [item.value for item in app.sidebar.caption]
    app.sidebar.selectbox[0].set_value("sam").run()
    assert not app.exception
    assert app.main.selectbox[0].value == "zh-Hans"
    assert app.query_params["coach_language"] == ["zh-Hans"]


@pytest.mark.parametrize("page,client,fixture", [
    ("transactions_page", WorkspaceDefaultsClient, "ui.transactions"),
    ("budget_page", WorkspaceDefaultsClient, "ui.budget"),
    ("goals_page", WorkspaceDefaultsClient, "ui.goals"),
    ("profile_page", SparseProfileClient, "ui.profile"),
    ("create_profile_page", SparseProfileClient, "ui.create_profile"),
])
def test_workspace_pages_use_selected_chinese_labels(page, client, fixture):
    app = AppTest.from_string(f"from ui.pages import {page}\n{page}()")
    app.session_state["backend_client"] = client()
    app.session_state["active_user_id"] = "synthetic-language"
    app.query_params["coach_language"] = "zh-Hans"
    app.run(timeout=30)
    assert not app.exception
    assert any(language_case(fixture) in item.value and "<h1" in item.value for item in app.markdown)
    if page == "transactions_page":
        assert language_case("ui.description") in [item.label for item in app.text_input]
        frame = app.dataframe[0].value
        assert language_case("ui.category") in frame.columns
        assert frame.iloc[0][language_case("ui.description")] == "Saved transaction"
        assert frame.iloc[0][language_case("ui.category")] == language_case("ui.housing")
    if page == "profile_page":
        assert language_case("ui.save_profile") in [item.label for item in app.button]
        # Labels/options are presentation; choices remain canonical enums.
        employment = app.selectbox(key="profile-synthetic-language-employment-status-v2")
        employment.set_value("employed")
        next(item for item in app.button if item.label == language_case("ui.save_profile")).click().run()
        assert not app.exception
        assert app.session_state["backend_client"].saved_profile["employment_status"] == "employed"


def test_direct_language_request_overrides_selection_and_syncs_controls():
    class RecordingClient(CoachClient):
        def ask_coach(self, payload):
            self.payload = payload
            result = super().ask_coach(payload)
            session = self.sessions[payload["session_id"]]
            session["messages"][-1]["explanation"]["trace_id"] = f"trace-fixture-{len(session['messages'])}"
            return result

    client = RecordingClient()
    app = AppTest.from_string("from ui.pages import coach_page\ncoach_page()")
    app.session_state["backend_client"] = client
    app.session_state["active_user_id"] = "synthetic-language"
    app.query_params["coach_language"] = "en"
    app.run()
    for message, expected in [
        (language_case("coach.chinese_question"), "en"),
        (language_case("coach.chinese_language_request"), "zh-Hans"),
        ("Explain compound interest. Please answer in English.", "en"),
    ]:
        app.chat_input[0].set_value(message).run(timeout=30)
        assert not app.exception
        assert client.payload["response_locale"] == expected
        assert client.payload["message"] == message
        assert app.query_params["coach_language"] == [expected]
        assert app.chat_input[0].placeholder == (
            language_case("coach.input") if expected == "zh-Hans" else "Message your financial coach"
        )


def test_fixture_response_displays_demo_capability_notice():
    app = AppTest.from_string(
        "from ui.pages import _render_coach_message\n"
        "_render_coach_message({'role': 'assistant', 'content': 'Example reply.', "
        "'explanation': {'model_provider': 'local_fixture'}}, 'en')"
    ).run()
    assert not app.exception
    assert any("offline fixture" in item.value for item in app.caption)


def test_profile_only_offers_supported_coach_languages():
    from ui.pages import LANGUAGE_OPTIONS
    assert LANGUAGE_OPTIONS == ["English", "Mandarin"]
