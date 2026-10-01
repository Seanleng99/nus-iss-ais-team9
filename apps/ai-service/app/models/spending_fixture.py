"""Conservative, offline-only spending fixture; production uses structured model extraction."""

import re
from datetime import date

ISO_DATE_PATTERN = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
SLASH_DATE_PATTERN = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?\b")
MARKED_AMOUNT_PATTERN = re.compile(
    r"(?:[$]|s\$\s*|sgd\s+)(\d{1,7}(?:[.,]\d{1,2})?)", re.IGNORECASE
)
BARE_AMOUNT_PATTERN = re.compile(
    r"(\d{1,7}(?:[.,]\d{1,2})?)(?:\s*(?:sgd|dollars?|s?\$\$?|bucks?))?", re.IGNORECASE
)
RECORD_VERB_PATTERN = re.compile(
    r"\b(?:spent|spend|paid|pays|pay|bought|buys|purchased|purchase|booked|"
    r"forked\s+out|shelled\s+out)\b\s+(.*)$",
    re.IGNORECASE,
)
SPEND_QUERY_PATTERN = re.compile(
    r"\b(?:what|how\s+much|when|which|show|list|tell)\b[^?.!]*"
    r"\b(?:spent|spending|spend|expenses?|transactions?|purchases?)\b",
    re.IGNORECASE,
)
RELATIVE_WORDS = re.compile(
    r"\b(?:today|yesterday|tonight|this\s+morning|last\s+\w+)\b", re.IGNORECASE
)


def _absolute_date(text: str):
    iso = ISO_DATE_PATTERN.search(text)
    if iso is not None:
        return f"{int(iso[1]):04d}-{int(iso[2]):02d}-{int(iso[3]):02d}"
    slash = SLASH_DATE_PATTERN.search(text)
    if slash is not None:
        day, month = int(slash[1]), int(slash[2])
        year = int(slash[3]) if slash[3] is not None else date.today().year
        if year < 100:
            year += 2000
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def _clean_description(rest: str) -> str | None:
    rest = re.sub(r"^(?:about|roughly|approx(?:imately)?)\s+", "", rest, flags=re.IGNORECASE)
    rest = re.sub(
        r"^(?:[$]\s*|s\$\s*|sgd\s+)?\d{1,7}(?:[.,]\d{1,2})?"
        r"(?:\s*(?:sgd|dollars?|bucks?|s?\$\$?))?\s*(?:on\s+|for\s+)?",
        "",
        rest,
        flags=re.IGNORECASE,
    )
    rest = ISO_DATE_PATTERN.sub(" ", rest)
    rest = SLASH_DATE_PATTERN.sub(" ", rest)
    rest = RELATIVE_WORDS.sub(" ", rest)
    rest = re.sub(r"\s+(?:on|for)\s*$", " ", rest)
    rest = re.sub(r"^(?:on|for)\s+", "", rest)
    rest = re.sub(r"\s{2,}", " ", rest).strip(" .,;:")
    return rest or None


def fixture_spending_draft(payload):
    message = str(payload["message"]).strip()
    pending = dict(payload.get("pending_draft") or {})

    if SPEND_QUERY_PATTERN.search(message):
        return {
            "is_spending_request": True,
            "action": "query",
            "query_date": _absolute_date(message),
            "transactions": [],
            "questions": [],
        }

    verb = RECORD_VERB_PATTERN.search(message)
    if verb is None:
        if pending:
            # A follow-up without a new record verb continues the pending draft;
            # relative dates are resolved by the backend, so nothing changes here.
            draft = dict(pending)
            draft["questions"] = []
            return draft
        return {"is_spending_request": False}

    marked = MARKED_AMOUNT_PATTERN.search(message)
    amount = None
    if marked is not None:
        amount = float(marked[1].replace(",", "."))
    else:
        bare = BARE_AMOUNT_PATTERN.search(SLASH_DATE_PATTERN.sub(" ", message))
        if bare is not None:
            amount = float(bare[1].replace(",", "."))
    description = _clean_description(verb[1])
    questions = []
    if amount is None:
        questions.append("How much did it cost?")
    if description is None:
        questions.append("What did you spend the money on?")
    return {
        "is_spending_request": True,
        "action": "record",
        "transactions": [
            {
                "description": description,
                "amount": amount,
                "category": None,
                "occurred_on": _absolute_date(message),
                "recurring": False,
                "booking": False,
            }
        ],
        "query_date": None,
        "questions": questions,
    }
