import ast
from pathlib import Path

from coach_i18n import catalog
from language_fixtures import language_case
from streamlit.testing.v1 import AppTest
from test_app import SparseProfileClient


def test_reviewed_static_interface_text_has_a_catalog_entry():
    root = Path(__file__).parents[1]
    known = {value.casefold() for key, value in catalog("en").items() if key.startswith("ui.")}
    missing = []
    for path in [root / "app.py", *list((root / "ui").rglob("*.py"))]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "ui_text" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.casefold() not in known
            ):
                missing.append((path.name, node.lineno, node.args[0].value))
    assert not missing, missing


def test_presentation_keeps_canonical_data_and_unreviewed_prose():
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui.i18n import display_frame, ui_message\n"
        "data = [{'Description': 'User supplied description', 'Amount': 125.50}]\n"
        "st.dataframe(display_frame(data))\n"
        "st.session_state['original_data'] = data\n"
        "st.write(ui_message('Unreviewed generated paragraph with arbitrary content.'))\n"
    )
    app.query_params["coach_language"] = "zh-Hans"
    app.run()
    assert not app.exception
    assert app.session_state["original_data"] == [
        {"Description": "User supplied description", "Amount": 125.50}
    ]
    assert app.dataframe[0].value.iloc[0][language_case("ui.description")] == "User supplied description"
    assert "Unreviewed generated paragraph with arbitrary content." in [item.value for item in app.markdown]


def test_switching_language_retains_unsaved_profile_inputs():
    app = AppTest.from_string(
        "from ui.coach_language import render_language_header\n"
        "from ui.pages import profile_page\n"
        "render_language_header('synthetic-language')\nprofile_page()"
    )
    app.session_state["backend_client"] = SparseProfileClient()
    app.session_state["active_user_id"] = "synthetic-language"
    app.run()
    app.text_input(key="profile-synthetic-language-display-name").set_value("Unsaved name")
    app.number_input(key="profile-synthetic-language-monthly-income").set_value(3450)
    app.selectbox(key="workspace-language-widget-en").set_value("zh-Hans").run()
    assert not app.exception
    assert app.text_input(key="profile-synthetic-language-display-name").value == "Unsaved name"
    assert app.number_input(key="profile-synthetic-language-monthly-income").value == 3450
    assert app.session_state["backend_client"].saved_profile is None
