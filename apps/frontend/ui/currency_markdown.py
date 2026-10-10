"""Protect currency dollar signs without changing code, link targets or maths."""

import re

from ui.telemetry import log_event

PROTECTED = re.compile(
    r"(?P<code>(?P<ticks>`+).*?(?P=ticks)|~~~.*?~~~)|"
    r"(?P<link>\]\([^\n)]*\))|(?P<display>\$\$.*?\$\$)",
    re.DOTALL,
)


def currency_safe_markdown(text: str) -> str:
    log_event("VV entering ", "ui.currency_markdown", "currency_safe_markdown")
    protected = [(match.start(), match.end()) for match in PROTECTED.finditer(text)]
    # Scan maths only in prose gaps, so a currency delimiter cannot swallow
    # a following code span or URL and prevent its protection.
    cursor = 0
    for start, end in [*protected, (len(text), len(text))]:
        for match in re.finditer(r"(?<![\\S])\$[^\n$]+\$", text[cursor:start]):
            body = re.sub(r"\\[A-Za-z]+", "", match.group()[1:-1])
            closing = cursor + match.end()
            if (
                re.search(r"[A-Za-z]{2,}", body)
                or not re.fullmatch(r"[A-Za-z0-9_\s.,+*/=()^{}%\-]+", body)
                or re.match(r"[ \t]*[-+]?\d", text[closing:])
            ):
                continue
            protected.append((cursor + match.start(), closing))
        cursor = end
    return re.sub(
        r"(?<!\\)\$(?=[ \t]*[-+]?\d)",
        lambda match: (
            match.group()
            if any(start <= match.start() < end for start, end in protected)
            else r"\$"
        ),
        text,
    )
