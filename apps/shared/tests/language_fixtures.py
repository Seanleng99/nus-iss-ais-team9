"""Independent multilingual test inputs and golden assertions."""

import json
from functools import cache
from pathlib import Path


@cache
def _cases() -> dict[str, str]:
    return json.loads(
        Path(__file__)
        .with_name("fixtures")
        .joinpath("language_cases.json")
        .read_text(encoding="utf-8")
    )


def language_case(key: str) -> str:
    return _cases()[key]
