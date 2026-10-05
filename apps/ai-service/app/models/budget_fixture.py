"""Conservative, offline-only budget fixture; production uses structured model extraction."""

import re
from datetime import date

from coach_math.calendar import financial_today

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


def fixture_budget_scope(text, today=None):
    """Offline calendar examples only; production uses the semantic router."""
    today = date.fromisoformat(today) if isinstance(today, str) else today or financial_today()
    lower = text.lower()
    if re.search(r"\ball\s+(?:(?:my|saved|existing)\s+)*budgets?\b", lower):
        return {"kind": "all"}, False
    names = "|".join(MONTHS)
    span = re.search(rf"\b({names})(?:\s+(20\d{{2}}))?\s+(?:through|to|until|[-\u2013])\s+({names})\s+(20\d{{2}})\b", lower)
    if span:
        start_year = int(span[2] or span[4])
        start_month, end_month = MONTHS.index(span[1]) + 1, MONTHS.index(span[3]) + 1
        if span[2] is None and start_month > end_month:
            start_year -= 1
        return {"kind": "range", "start": f"{start_year}-{start_month:02d}-01", "end": f"{span[4]}-{end_month:02d}-01"}, False
    dates = [f"{year}-{int(month):02d}-01" for year, month in re.findall(r"\b(20\d{2})-(0[1-9]|1[0-2])(?:-01)?\b", lower)]
    dates += [f"{year}-{MONTHS.index(month) + 1:02d}-01" for month, year in re.findall(rf"\b({names})\s+(20\d{{2}})\b", lower)]
    if dates:
        return {"kind": "periods", "periods": list(dict.fromkeys(dates))}, False
    year = re.search(r"\b(20\d{2})\b", lower)
    if year and not re.search(rf"\b({names})\b", lower):
        return {"kind": "range", "start": f"{year[1]}-01-01", "end": f"{year[1]}-12-01"}, False
    relative = re.search(r"\b(this|last|next)\s+(month|year)\b", lower)
    if relative:
        offset = {"this": 0, "last": -1, "next": 1}[relative[1]]
        if relative[2] == "year":
            year = today.year + offset
            return {"kind": "range", "start": f"{year}-01-01", "end": f"{year}-12-01"}, False
        year, month = divmod(today.year * 12 + today.month - 1 + offset, 12)
        return {"kind": "periods", "periods": [f"{year}-{month + 1:02d}-01"]}, False
    return {"kind": "default"}, bool(re.search(rf"\b({names})\b", lower))


def fixture_record_request(payload):
    text = payload["message"]
    previous = (payload.get("pending_draft") or {}).get("workspace") or {}
    lower = text.lower()
    records = bool(re.search(r"\bbudgets?\b", lower) and re.search(
        r"\b(show|list|read|summari[sz]e|delete|remove|edit|update|change|compare)\b", lower))
    if not records and previous.get("operation") != "budgets":
        return None
    if "what if" in lower or "scenario" in lower or "review" in lower or "compare budget methods" in lower:
        return None
    if re.search(r"50/30/20|80/20|zero[- ]based|savings first|custom percentages|flexible method", lower):
        return None
    import json
    command = json.loads(previous["payload_json"]) if previous.get("operation") == "budgets" else {}
    command.setdefault("action", "read")
    scope, unclear = fixture_budget_scope(text, payload.get("recorded_context", {}).get("today"))
    if scope["kind"] != "default" or "scope" not in command:
        command["scope"] = scope
    if re.search(r"\b(delete|remove)\b.*\b(?:monthly )?budgets?\b", lower) and "category" not in lower and "limit" not in lower:
        command["action"] = "delete"
    elif re.search(r"\b(edit|update|change|remove|delete)\b", lower):
        command["action"] = "edit"
    elif "compare" in lower:
        command["action"] = "compare"
    changes = [{"category": match[1].strip().lower(), "limit_amount": float(match[2])}
               for match in re.finditer(r"(?:^|[;\n,])\s*([\w ]+):\s*(?:SGD\s*|\$)?(\d+(?:\.\d{1,2})?)", text, re.IGNORECASE)]
    if changes:
        command["categories"] = changes
    removal = re.search(r"\bremove (?:the )?([\w ]+?) (?:category|limit)\b", lower)
    if removal:
        command["remove_categories"] = [removal[1].strip()]
    return {"action": "workspace", "workspace": {"operation": "budgets", "payload_json": json.dumps(command)},
            "questions": ["Which month and year should I use?"] if unclear else []}


def fixture_budget_draft(payload):
    records = fixture_record_request(payload)
    if records is not None:
        return records
    text = payload["message"].strip()
    scenario = re.search(r"scenario ([A-Za-z0-9 _-]+): (income|savings|[a-z ]+)=(\d+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if scenario:
        text = text[:scenario.start()] + text[scenario.end():]
    draft = dict(payload.get("pending_draft") or {})
    draft.setdefault("period_start", None)
    if draft.get("currency") is None:
        draft["currency"] = "SGD"
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
    currency = re.search(r"\b(SGD|USD|EUR|GBP|AUD|MYR|JPY|CNY|HKD)\b|S\$", text, re.IGNORECASE)
    if currency:
        draft["currency"] = (currency[1] or "SGD").upper()
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
    if any(phrase in text.lower() for phrase in ("multi-month", "carry forward", "rollover", "periodic budget review")):
        draft["action"] = "continuity"
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
    elif not draft["categories"] and not draft.get("planning") and draft.get("action") not in {"review", "alternatives", "continuity"}:
        draft["questions"] = [
            "For offline mode, provide limits as 'food: 500, transport: 150', plus month and year. All amounts use SGD."
        ]
    return draft
