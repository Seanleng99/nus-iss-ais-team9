"""Translate reviewed interface text without rewriting user or model content."""

import re
from functools import cache
from string import Formatter

from coach_i18n import catalog, translate

from ui.coach_language import current_selection
from ui.telemetry import log_event


@cache
def _interface_keys() -> dict[str, str]:
    log_event("VV entering ", "ui.i18n", "_interface_keys")
    return {text.casefold(): key for key, text in catalog("en").items() if key.startswith("ui.")}


def ui_text(text: str, *, locale: str | None = None, **values) -> str:
    log_event("VV entering ", "ui.i18n", "ui_text")
    key = _interface_keys().get(text.casefold())
    if key:
        return translate(key, locale or current_selection(), **values)
    return text.format(**values) if values else text


@cache
def _message_patterns():
    log_event("VV entering ", "ui.i18n", "_message_patterns")
    patterns = []
    for key, template in catalog("en").items():
        if not key.startswith("ui.message."):
            continue
        fragments = []
        for literal, field, _, _ in Formatter().parse(template):
            fragments.append(re.escape(literal))
            if field:
                fragments.append(f"(?P<{field}>.+?)")
        patterns.append((key, re.compile("".join(fragments), re.DOTALL)))
    return patterns


def ui_message(text: str) -> str:
    """Localize allowlisted deterministic service messages, never chat prose."""
    log_event("VV entering ", "ui.i18n", "ui_message")
    if current_selection() == "en":
        return text
    for key, pattern in _message_patterns():
        match = pattern.fullmatch(text)
        if match:
            values = match.groupdict()
            return "".join(
                literal + (ui_text(values[field]) if field else "")
                for literal, field, _, _ in Formatter().parse(catalog("zh-Hans")[key])
            )
    return ui_text(text)


def option_label(value: str, locale: str | None = None) -> str:
    # Stored enum/category identifiers stay canonical; only their display changes.
    log_event("VV entering ", "ui.i18n", "option_label")
    english = value.replace("_", " ").title()
    selected = locale or current_selection()
    return ui_text(english, locale=selected) if selected == "zh-Hans" else english


def option_formatter():
    log_event("VV entering ", "ui.i18n", "option_formatter")
    locale = current_selection()
    return lambda value: option_label(value, locale)


def text_formatter(labels: dict[str, str]):
    log_event("VV entering ", "ui.i18n", "text_formatter")
    locale = current_selection()
    return lambda value: ui_text(labels[value], locale=locale)


def display_frame(frame):
    """Localize presentation columns on a copy; retain canonical data keys."""
    log_event("VV entering ", "ui.i18n", "display_frame")
    if isinstance(frame, list):
        return [{ui_text(key): value for key, value in row.items()} for row in frame]
    return frame.rename(columns=ui_text)


def month_label(value, locale: str | None = None) -> str:
    log_event("VV entering ", "ui.i18n", "month_label")
    return value.strftime("%Y-%m" if (locale or current_selection()) == "zh-Hans" else "%B %Y")


def month_formatter():
    log_event("VV entering ", "ui.i18n", "month_formatter")
    locale = current_selection()
    return lambda value: month_label(value, locale)
