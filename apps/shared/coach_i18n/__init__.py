"""Language selection and reviewed fixed messages shared by all services."""

import json
import re
from functools import cache, lru_cache
from importlib.resources import files
from string import Formatter
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
    """Recognize direct language requests; quoted examples are not preferences."""
    text = re.sub(
        r"```[\s\S]*?```|`[^`]*`|\"[^\"]*\"|(?<!\w)'[^'\n]{1,120}'(?!\w)",
        " ", message[:12000],
    )
    requests = []
    for locale, patterns in load_data("language_requests").items():
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                before = text[max(0, match.start() - 20):match.start()]
                if re.search(r"\b(?:do not|don't|never|not)\s*$", before, re.IGNORECASE):
                    continue
                if re.search(
                    r"\b(?:do not|don't|never)\s+(?:answer|reply|respond|explain|write|speak|use)\b",
                    match[0], re.IGNORECASE,
                ):
                    continue
                requests.append((match.end(), locale))
    return max(requests, default=(0, None))[1]


def _detected_locale(message: str) -> SupportedLocale | None:
    scripts = load_data("scripts")
    if re.search(scripts["non_chinese_fallback_scripts"], message):
        return None
    han = len(re.findall(scripts["han_basic"], message))
    latin = len(re.findall(r"[A-Za-z]", message))
    if han >= 2 and han * 2 >= latin:
        return "zh-Hans"
    if latin:
        return "en"
    return None


def resolve_locale(
    message: str, *, selected: object = None, preferred: object = None, history=()
) -> SupportedLocale:
    """Current requests win; settings and recent user dialogue provide defaults."""
    requested = explicit_locale(message)
    if requested:
        return requested
    selected_locale = normalize_locale(selected)
    if selected_locale:
        return selected_locale
    users = []
    for item in list(history)[-8:]:
        role = item.get("role") if isinstance(item, dict) else getattr(item, "role", None)
        content = item.get("content", "") if isinstance(item, dict) else getattr(item, "content", "")
        if role == "user" and isinstance(content, str):
            users.append(content[:1500])
    for content in reversed(users):
        requested = explicit_locale(content)
        if requested:
            return requested
    preferred_locale = normalize_locale(preferred)
    if preferred_locale:
        return preferred_locale
    detected = _detected_locale(message[:12000])
    if detected:
        return detected
    for content in reversed(users):
        detected = _detected_locale(content)
        if detected:
            return detected
    return "en"


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


@cache
def _backend_templates():
    templates = []
    for key, template in catalog("en").items():
        if not key.startswith(("goal_action.", "budget_action.", "coach_action.", "ui.message.")):
            continue
        parts, seen = [], set()
        for literal, field, _, _ in Formatter().parse(template):
            parts.append(re.escape(literal))
            if field:
                parts.append(f"(?P<{field}>.+?)" if field not in seen else f"(?P={field})")
                seen.add(field)
        if seen:
            templates.append((key, re.compile("".join(parts), re.DOTALL)))
    return templates


def localize_backend_text(text: str, locale: object) -> str:
    """Render reviewed deterministic backend text; never pass model prose here.

    Match complete templates and leave captured user names, values and unknown
    questions intact. Language changes cannot change the validated action.
    """
    if normalize_locale(locale) != "zh-Hans":
        return text
    exact = localize_reviewed(text, locale)
    if exact != text:
        return exact
    if "\n" in text:
        return "\n".join(localize_backend_text(line, locale) for line in text.split("\n"))
    for key, pattern in _backend_templates():
        match = pattern.fullmatch(text)
        if match:
            values = match.groupdict()
            for field in (
                "change", "source", "note", "details", "status", "limit", "relationship",
                "kind", "frequency", "enabled", "pattern", "rule", "operation", "treatment",
                "effect", "strategy", "months",
                "method", "condition",
            ):
                if field in values:
                    values[field] = localize_backend_text(values[field], locale)
            if key.startswith("goal_action.") and "description" in values:
                values["description"] = localize_backend_text(values["description"], locale)
            if key == "budget_action.validation_fields":
                issues = []
                for issue in values["issues"].split("; "):
                    field, separator, detail = issue.partition(": ")
                    if separator and re.fullmatch(r"[A-Za-z0-9_.]+", field):
                        detail = detail.removeprefix("Value error, ")
                        issue = field + ": " + localize_backend_text(detail, locale)
                    issues.append(issue)
                values["issues"] = "; ".join(issues)
            return translate(key, locale, **values)
    # Prefixes are reviewed literal sentences; only their deterministic suffix
    # is considered for another complete reviewed template.
    for key, english in catalog("en").items():
        if key.startswith(("goal_action.", "budget_action.")) and english.endswith(". ") and text.startswith(english):
            return translate(key, locale) + localize_backend_text(text[len(english):], locale)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    if len(sentences) > 1:
        return " ".join(localize_backend_text(sentence, locale) for sentence in sentences)
    return text


def topic_label(topic: str, locale: object, *, capitalize: bool = False) -> str:
    if normalize_locale(locale) == "zh-Hans":
        return load_data("education_vocabulary")["CHINESE_GAP_LABELS"].get(topic, topic)
    return topic.capitalize() if capitalize else topic
