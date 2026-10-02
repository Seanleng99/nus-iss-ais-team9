import re
from string import Formatter
from types import SimpleNamespace

import pytest
from coach_i18n import (
    catalog,
    input_pattern,
    localize_reviewed,
    normalize_locale,
    request_locale,
    resolve_locale,
    task_language,
    translate,
)
from language_fixtures import language_case


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Explain diversification in Chinese.", "zh-Hans"),
        ("Please answer in Mandarin.", "zh-Hans"),
        ("Explain ETFs in English, then answer in Chinese.", "zh-Hans"),
        (language_case("language.test_explicit_request_and_bounded_detection"), "en"),
        (language_case("language.test_explicit_request_and_bounded_detection_2"), "en"),
        (
            language_case("language.test_explicit_request_and_bounded_detection_3"),
            "zh-Hans",
        ),
        (language_case("language.test_explicit_request_and_bounded_detection_4"), "en"),
        (language_case("language.test_explicit_request_and_bounded_detection_5"), "en"),
        ("Compare ETFs and bonds.", "en"),
    ],
)
def test_explicit_request_and_bounded_detection(message, expected):
    assert resolve_locale(message) == expected


def test_explicit_request_selection_session_preference_and_detection_precedence():
    history = [{"role": "user", "content": "Answer in Chinese."}]
    assert (
        resolve_locale(
            language_case(
                "language.test_explicit_request_selection_session_preference_and_detection_precedence"
            ),
            selected="zh-Hans",
            preferred="Mandarin",
            history=history,
        )
        == "en"
    )
    assert (
        resolve_locale(
            "Explain ETFs.", selected="en", preferred="Mandarin", history=history
        )
        == "en"
    )
    assert (
        resolve_locale("Give an example.", preferred="English", history=history)
        == "zh-Hans"
    )
    assert resolve_locale("Explain ETFs.", preferred="Mandarin") == "zh-Hans"
    # Assistant text must not change the user's language preference.
    assert (
        resolve_locale(
            "Explain ETFs.",
            history=[{"role": "assistant", "content": "Answer in Chinese."}],
        )
        == "en"
    )


def test_request_and_restricted_task_agree_without_exposing_financial_snapshot():
    request = SimpleNamespace(
        message="Explain ETFs.",
        response_locale=None,
        snapshot=SimpleNamespace(preferences={"preferred_language": "Mandarin"}),
        conversation_context=[],
    )
    selected = request_locale(request)
    task = SimpleNamespace(
        sanitized_message=request.message,
        context_features={"response_locale": selected},
    )
    assert selected == "zh-Hans"
    assert task_language(task) == "Chinese"


def test_catalogs_have_matching_keys_and_interpolation_contracts():
    english, chinese = catalog("en"), catalog("zh-Hans")
    assert english.keys() == chinese.keys()
    formatter = Formatter()
    for key in english:
        en_fields = {field for _, field, _, _ in formatter.parse(english[key]) if field}
        zh_fields = {field for _, field, _, _ in formatter.parse(chinese[key]) if field}
        assert en_fields == zh_fields, key


def test_only_exact_reviewed_text_is_localized():
    english = translate("privacy.other_user_data", "en")
    assert localize_reviewed(english, "zh-Hans") == translate(
        "privacy.other_user_data", "zh-Hans"
    )
    assert (
        localize_reviewed("UNREVIEWED_MODEL_PAYLOAD", "zh-Hans")
        == "UNREVIEWED_MODEL_PAYLOAD"
    )
    with pytest.raises(KeyError):
        translate("nonexistent.message", "zh-Hans")
    with pytest.raises(KeyError):
        translate("education.uncovered_topics", "zh-Hans")


def test_supported_aliases_and_unsupported_preference_fallback():
    assert normalize_locale("Mandarin") == "zh-Hans"
    assert normalize_locale("zh-SG") == "zh-Hans"
    assert normalize_locale("Tamil") is None
    assert normalize_locale("zh-Hant") is None
    assert resolve_locale("Explain ETFs.", preferred="Tamil") == "en"


def test_input_templates_preserve_bounded_captures_and_regex_fragments():
    duration = re.compile(
        input_pattern(
            "backend.services.session_context.goal_target_months",
            PREFIX="",
            SEPARATOR=r"\s+",
        )
    )
    assert (
        duration.fullmatch(language_case("recognition.goal_duration"))["value"] == "12"
    )
    assert duration.fullmatch(language_case("recognition.oversized_duration")) is None
    goal_name = re.compile(
        input_pattern(
            "backend.services.session_context.goal_name", PREFIX="", SEPARATOR=r"\s+"
        )
    )
    assert (
        goal_name.fullmatch(language_case("recognition.goal_name"))["value"]
        == "Emergency fund"
    )
