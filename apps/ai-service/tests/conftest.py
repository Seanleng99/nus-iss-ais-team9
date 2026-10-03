"""Opt-in JUnit metadata for investment test questions and responses."""

from __future__ import annotations

import json

import pytest

_QUESTION_PARAMETER_NAMES = ("question", "message", "prompt", "attack", "instruction", "text")


def pytest_addoption(parser):
    parser.addoption(
        "--investment-report",
        action="store_true",
        default=False,
        help="include safe question/input text and agent responses in JUnit testcase properties",
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


@pytest.fixture
def record_investment_response(request):
    """Attach actual workflow responses to JUnit only for explicit investment reports."""
    if not request.config.getoption("--investment-report"):
        return lambda question, answer, *, source: None

    def record(question, answer, *, source):
        if answer is not None and not isinstance(answer, str):
            return
        value = json.dumps(
            {"question": question, "answer": answer, "source": source},
            ensure_ascii=False,
        )
        request.node.user_properties.append(("test_response", value))

    return record
