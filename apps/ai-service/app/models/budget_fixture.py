"""Conservative, offline-only budget fixture; production uses structured model extraction."""

import re

MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def fixture_budget_draft(payload):
    text = payload["message"].strip()
    draft = dict(payload.get("pending_draft") or {})
    draft.setdefault("period_start", None)
    draft.setdefault("currency", None)
    draft.setdefault("categories", [])
    draft["questions"] = []
    draft["is_budget_request"] = True
    date_match = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])(?:-01)?\b", text)
    if date_match:
        draft["period_start"] = f"{date_match[1]}-{date_match[2]}-01"
        text = text.replace(date_match[0], "")
    for index, month in enumerate(MONTHS, 1):
        match = re.search(rf"\b{month}\s+(20\d{{2}})\b", text, re.IGNORECASE)
        if match:
            draft["period_start"] = f"{match[1]}-{index:02d}-01"
            text = text.replace(match[0], "")
    if re.search(r"\bSGD\b|S\$", text, re.IGNORECASE):
        draft["currency"] = "SGD"
    entries = []
    # Deliberately require 'category: amount' in the offline fixture.
    for match in re.finditer(
        r"(?:^|[,;\n])\s*([\w ]{1,64}?)\s*[:=]\s*(?:SGD\s*|S\$|\$)?(\d+(?:\.\d{1,2})?)(?=\s*(?:SGD)?\s*(?:[,;\n]|$))",
        text,
        re.IGNORECASE,
    ):
        entries.append({"category": match[1].strip().lower(), "limit_amount": float(match[2])})
    if entries:
        existing = {item["category"]: item for item in draft["categories"]}
        existing.update({item["category"]: item for item in entries})
        draft["categories"] = list(existing.values())
    elif not draft["categories"]:
        draft["questions"] = [
            "For offline mode, provide limits as 'food: 500, transport: 150', plus month, year and SGD currency."
        ]
    return draft
