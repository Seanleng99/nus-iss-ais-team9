"""Opt-in JUnit metadata for investment test questions."""

from __future__ import annotations

_QUESTION_PARAMETER_NAMES = ("question", "message", "prompt", "attack", "instruction", "text")


def pytest_addoption(parser):
    parser.addoption(
        "--investment-report",
        action="store_true",
        default=False,
        help="include safe question/input text in JUnit testcase properties",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--investment-report"):
        return

    for item in items:
        marker = item.get_closest_marker("test_questions")
        questions = marker.args if marker else ()
        if not questions:
            callspec = getattr(item, "callspec", None)
            params = getattr(callspec, "params", {})
            questions = tuple(
                str(params[name])
                for name in _QUESTION_PARAMETER_NAMES
                if name in params and isinstance(params[name], str)
            )

        item.user_properties.extend(
            ("test_question", question) for question in questions if isinstance(question, str)
        )
