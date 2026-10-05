"""Bounded offline recurrence fixtures; production uses the structured extractor."""

import re


def apply_recurring_terms(payload, draft):
    message = str(payload["message"])
    # This bounded recognizer is an offline fixture only. Production intent
    # is extracted semantically into the typed SpendingDraft contract.
    if draft.get("action") == "record" and re.search(
        r"\b(?:for (?:me to )?review|do not save|don't save|without saving|"
        r"before saving|preview (?:it|this|these))\b", message, re.IGNORECASE
    ):
        draft["persistence_intent"] = "preview"
    if not draft.get("transactions") and re.search(
        r"\b(?:forecast|project|estimate|upcoming)\b.*\b(?:recurring|expenses?|bills?)\b", message, re.IGNORECASE
    ):
        dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", message)
        return {"is_spending_request": True, "action": "forecast", "transactions": [],
                "query_start": dates[0] if len(dates) == 2 else None,
                "query_end": dates[1] if len(dates) == 2 else None, "questions": []}
    match = re.search(r"\b(monthly|weekly|fortnightly|yearly|annually)\b|"
                      r"\bevery\s+(\d+)\s+(weeks?|months?|years?)\b", message, re.IGNORECASE)
    month_end = bool(re.search(r"\b(?:month[- ]end|last day of (?:every|each|the) month)\b", message, re.IGNORECASE))
    if (not match and not month_end) or draft.get("action") != "record":
        return draft
    if match is None:
        frequency, interval = "monthly", 1
    elif match[1]:
        frequency = "yearly" if match[1].lower() == "annually" else match[1].lower()
        interval = 1
    else:
        frequency = {"week": "weekly", "month": "monthly", "year": "yearly"}[match[3].lower().rstrip("s")]
        interval = int(match[2])
    for item in draft.get("transactions", []):
        item["recurring"] = True
        item["recurrence"] = {"frequency": frequency, "interval": interval,
                              "month_end": month_end,
                              "first_on": None, "next_due_on": None, "last_on": None}
        if item.get("description"):
            item["description"] = re.sub(r"\b(?:monthly|weekly|fortnightly|yearly|annually)\b|"
                                         r"\bevery\s+\d+\s+(?:weeks?|months?|years?)\b", "",
                                         item["description"], flags=re.IGNORECASE).strip()
    return draft
