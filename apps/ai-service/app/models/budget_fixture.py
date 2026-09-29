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
    scenario = re.search(r"scenario ([A-Za-z0-9 _-]+): (income|savings|[a-z ]+)=(\d+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if scenario:
        text = text[:scenario.start()] + text[scenario.end():]
    draft = dict(payload.get("pending_draft") or {})
    draft.setdefault("period_start", None)
    draft.setdefault("currency", None)
    draft.setdefault("categories", [])
    draft["questions"] = []
    draft["is_budget_request"] = True
    if payload.get("planning_requested") or draft.get("planning"):
        planning = dict(draft.get("planning") or {})
        for key, pattern in (
            ("take_home_income", r"(?:take.home(?: income)?|net income)\s*[:=]?\s*(?:SGD\s*)?(\d+(?:\.\d{1,2})?)"),
            ("savings_target", r"savings(?: target)?\s*[:=]?\s*(?:SGD\s*)?(\d+(?:\.\d{1,2})?)"),
        ):
            matched = re.search(pattern, text, re.IGNORECASE)
            if matched:
                planning[key] = float(matched[1])
                if key == "take_home_income":
                    planning["income_basis"] = "take_home"
        if "all expenses included" in text.lower():
            planning["expenses_confirmed"] = True
        if "use recorded spending" in text.lower():
            planning["use_recorded_spending"] = True
        for phrase, method in (("50/30/20", "50_30_20"), ("80/20", "80_20"), ("zero-based", "zero_based"), ("savings first", "pay_yourself_first"), ("flexible method", "flexible")):
            if phrase in text.lower():
                planning["method"] = {"name": method}
        draft["planning"] = planning
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
    if draft.get("planning") and any(word in text.lower() for word in ("compare", "what if")):
        draft["action"] = "compare"
    if scenario and draft.get("planning"):
        name, field, value = scenario.groups()
        item = {"name": name.strip()}
        if field.lower() in {"income", "savings"}:
            item["take_home_income" if field.lower() == "income" else "savings_target"] = float(value)
        else:
            item["categories"] = [{"category": field.strip().lower(), "limit_amount": float(value)}]
        draft["action"] = "compare"
        draft["scenarios"] = [item]
    if "review" in text.lower() or "month-end pace" in text.lower():
        draft["action"] = "review"
    if "funded alternatives" in text.lower():
        draft["action"] = "alternatives"
    entries = []
    # Deliberately require 'category: amount' in the offline fixture.
    for match in re.finditer(
        r"(?:^|[,;\n])\s*([\w ]{1,64}?)\s*[:=]\s*(?:SGD\s*|S\$|\$)?(\d+(?:\.\d{1,2})?)(?=\s*(?:SGD)?\s*(?:[,;\n]|$))",
        text,
        re.IGNORECASE,
    ):
        category = match[1].strip().lower()
        if draft.get("planning") and category in {"savings", "savings target", "take home", "take home income", "net income"}:
            continue
        entries.append({"category": category, "limit_amount": float(match[2])})
    if entries:
        existing = {item["category"]: item for item in draft["categories"]}
        existing.update({item["category"]: item for item in entries})
        draft["categories"] = list(existing.values())
    elif not draft["categories"] and not draft.get("planning") and draft.get("action") not in {"review", "alternatives"}:
        draft["questions"] = [
            "For offline mode, provide limits as 'food: 500, transport: 150', plus month, year and SGD currency."
        ]
    return draft
