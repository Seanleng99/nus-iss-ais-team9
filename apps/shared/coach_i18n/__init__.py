"""Language selection and reviewed fixed messages shared by all services."""

import json
import re
from functools import cache, lru_cache
from importlib.resources import files
from typing import Literal

SupportedLocale = Literal["en", "zh-Hans"]


def normalize_locale(value: object) -> SupportedLocale | None:
    if not isinstance(value, str):
        return None
    alias = value.strip().casefold().replace("_", "-")
    for locale, language in load_data("languages").items():
        if alias in language["aliases"]:
            return locale
    return None


@cache
def load_data(name: str) -> dict:
    # Only application-owned resource names are accepted.
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError("Invalid language resource name")
    return json.loads(
        files(__package__).joinpath("data", name + ".json").read_text(encoding="utf-8")
    )


def input_pattern(key: str, **parts: str) -> str:
    """Read an application-owned recognition rule, with optional regex fragments.

    Rules are independent of the output locale: safety checks recognize all
    supported input languages. Only callers supply trusted regex fragments.
    """
    pattern = load_data("input_patterns")[key]
    return pattern.format(**parts) if parts else pattern


def explicit_locale(message: str) -> SupportedLocale | None:
    """Recognize bounded output-language requests; the latest request wins."""
    matches = []
    for locale, patterns in load_data("language_requests").items():
        for pattern in patterns:
            matches.extend(
                (m.end(), locale) for m in re.finditer(pattern, message, re.IGNORECASE)
            )
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def resolve_locale(
    message: str, *, selected: object = None, preferred: object = None, history=()
) -> SupportedLocale:
    explicit = explicit_locale(message)
    if explicit:
        return explicit
    selection = normalize_locale(selected)
    if selection:
        return selection
    for item in reversed(history):
        role = item.get("role") if isinstance(item, dict) else item.role
        content = item.get("content", "") if isinstance(item, dict) else item.content
        if role == "user" and (previous := explicit_locale(content)):
            return previous
    preference = normalize_locale(preferred)
    if preference:
        return preference
    # Han characters alone cannot distinguish Chinese from Japanese. Exclude
    # kana/Hangul; unsupported languages fall back to English. Preference wins.
    if re.search(load_data("scripts")["non_chinese_fallback_scripts"], message):
        return "en"
    return "zh-Hans" if re.search(load_data("scripts")["han_basic"], message) else "en"


def request_locale(request) -> SupportedLocale:
    return resolve_locale(
        request.message,
        selected=getattr(request, "response_locale", None),
        preferred=request.snapshot.preferences.get("preferred_language"),
        history=getattr(request, "conversation_context", ()),
    )


def language_name(locale: object) -> str:
    """Preserve the existing English/Chinese prompt and audit contract."""
    return load_data("languages")[normalize_locale(locale) or "en"]["name"]


def response_language(request) -> str:
    return language_name(request_locale(request))


def task_language(task) -> str:
    return language_name(
        resolve_locale(
            task.sanitized_message,
            selected=task.context_features.get("response_locale"),
            history=task.context_features.get("conversation_context", ()),
        )
    )


@lru_cache(maxsize=2)
def catalog(locale: SupportedLocale) -> dict[str, str]:
    return json.loads(
        files(__package__)
        .joinpath("locales", locale + ".json")
        .read_text(encoding="utf-8")
    )


def translate(key: str, locale: object = "en", **values) -> str:
    """Render a reviewed message, falling back to English for missing translations.

    Unknown keys and missing values fail loudly. Never translate blocked drafts.
    """
    selected = normalize_locale(locale) or "en"
    template = catalog(selected).get(key, catalog("en")[key])
    return template.format(**values)


def localize_reviewed(text: str, locale: object) -> str:
    """Localize exact catalog text; leave generated content to the model."""
    for key, english in catalog("en").items():
        if text in (english, catalog("zh-Hans").get(key)):
            return translate(key, locale)
    return text


def topic_label(topic: str, locale: object, *, capitalize: bool = False) -> str:
    if normalize_locale(locale) == "zh-Hans":
        return load_data("education_vocabulary")["CHINESE_GAP_LABELS"].get(topic, topic)
    return topic.capitalize() if capitalize else topic
