from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_multipage_app_renders_without_runtime_errors() -> None:
    app = AppTest.from_file(Path(__file__).parents[1] / "app.py").run(timeout=30)
    assert not app.exception
    assert app.sidebar.text_input[0].label == "Profile ID"
    assert app.sidebar.selectbox[0].label == "Period"
