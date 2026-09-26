import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.financial_schemas import TransactionCreate
from app.core.telemetry import log_event
from app.domain.schemas import CoachRequest, CoachResponse, MoneyAmount
from app.infrastructure.repositories import SQLAlchemyTransactionRepository

PENDING_TTL_SECONDS = 600.0

CANCEL_PATTERN = re.compile(
    r"^(?:please\s+|ok\s+|okay\s+)?(?:cancel(?:\s+it)?|never\s*mind|forget\s+(?:it|that)|"
    r"skip(?:\s+it)?)$",
    re.IGNORECASE,
)

QUESTION_PREFIXES = frozenset(
    {
        "how",
        "what",
        "when",
        "where",
        "why",
        "who",
        "which",
        "can",
        "could",
        "would",
        "should",
        "will",
        "do",
        "does",
        "did",
        "is",
        "are",
        "am",
        "review",
        "show",
        "tell",
        "explain",
        "help",
        "give",
    }
)

SPEND_VERB_PATTERN = re.compile(
    r"\b(?:spent|spends|paid|pays|bought|buys|purchased|purchases|took|take|takes|"
    r"booked|book|books|reserved|reserve|forked\s+out|shelled\s+out)\b",
    re.IGNORECASE,
)

BOOKING_PATTERN = re.compile(r"\b(?:booked|book|books|reserved|reserve|reservation)\b", re.IGNORECASE)

MARKED_AMOUNT_PATTERN = re.compile(
    r"(?:(?:[$]|s\$)\s*|sgd\s+)(\d{1,7}(?:[.,]\d{1,2})?)"
    r"|(\d{1,7}(?:[.,]\d{1,2})?)\s*(?:sgd|dollars?|s\$)\b",
    re.IGNORECASE,
)
BARE_AMOUNT_PATTERN = re.compile(
    r"(?<![\d/.,])\d{1,7}(?:[.,]\d{1,2})?(?![\d/])"
)
LEADING_AMOUNT_PATTERN = re.compile(
    r"^\s*(?:s?\$|sgd\s+)\s*(\d{1,7}(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)

WEEKDAY_NAMES = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

MONTH_NAMES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

WEEKDAY_ALTERNATIVES = "|".join(sorted(WEEKDAY_NAMES, key=len, reverse=True))
MONTH_ALTERNATIVES = "|".join(sorted(MONTH_NAMES, key=len, reverse=True))

DATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^(today|yesterday)$"),
    re.compile(r"^(?:a|one|\d{1,3})\s+days?\s+ago$"),
    re.compile(rf"^({WEEKDAY_ALTERNATIVES})$"),
    re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?$"),
    re.compile(rf"^(\d{1,2})\s+({MONTH_ALTERNATIVES})(?:\s+(\d{{2}}|\d{{4}}))?$"),
    re.compile(rf"^({MONTH_ALTERNATIVES})\s+(\d{{1,2}})(?:\s+(\d{{2}}|\d{{4}}))?$"),
]

INLINE_DATE_PATTERN = re.compile(
    rf"(?:\b(?:today|yesterday)\b"
    rf"|\b(?:the\s+)?day\s+before(?:\s+yesterday)?\b(?!\s+\w)"
    rf"|\b\d{{1,3}}\s+days?\s+ago\b"
    rf"|\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b"
    rf"|\b(?:the\s+)?\d{{1,2}}(?:st|nd|rd|th)\s+of\s+(?:{MONTH_ALTERNATIVES})\b(?:\s+\d{{2,4}})?"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)\s+(?:{MONTH_ALTERNATIVES})\b(?:\s+\d{{2,4}})?"
    rf"|\b(?:{MONTH_ALTERNATIVES})\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:\s+\d{{2,4}})?"
    rf"|\b(?:the\s+)?\d{{1,2}}(?:st|nd|rd|th)\b"
    rf"|\b\d{{1,2}}\s+(?:{MONTH_ALTERNATIVES})\b(?:\s+\d{{2,4}})?"
    rf"|\b(?:{WEEKDAY_ALTERNATIVES})\b)",
    re.IGNORECASE,
)

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("food", ("chicken rice", "lunch", "dinner", "breakfast", "makan", "kopi", "food",
              "grocer", "restaurant", "cafe", "café", "hawker", "mcdonald", "starbucks",
              "bubble tea", "din tai fung", "coffee", "bubbletea")),
    ("transport", ("mrt", "grab", "bus", "taxi", "train", "uber", "lyft", "petrol", "fuel",
                   "parking", "carpark", "erp", "top-up", "topup", "transit", "commute",
                   "scoot", "rideshare")),
    ("housing", ("rent", "mortgage", "maintenance fee", "service charge", "condo", "hdb")),
    ("utilities", ("electricity", "water bill", "gas bill", "internet", "broadband",
                   "mobile plan", "phone bill", "singtel", "starhub", "m1 ")),
    ("healthcare", ("doctor", "clinic", "medicine", "paracetamol", "pharmac", "hospital",
                    "dental", "gp ", "supplement")),
    ("education", ("course", "tuition", "class fee", "textbook", "training", "workshop",
                   "school", "university", "certification")),
    ("entertainment", ("movie", "cinema", "netflix", "spotify", "disney", "concert",
                       "game", "gaming", "karaoke", "zoo", "universal studios", "theme park")),
    ("shopping", ("shoes", "clothes", "shirt", "pants", "dress", "bag", "amazon", "shopee",
                  "lazada", "electronics", "headphone", "mouse", "keyboard", "gift")),
]


def _today() -> date:
    return datetime.now(UTC).date()


@dataclass
class CaptureDraft:
    amount: float
    description: str
    category: str
    booking: bool = False


class PendingCaptureStore:
    def __init__(self, ttl_seconds: float = PENDING_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[CaptureDraft, float]] = {}

    def put(self, user_id: str, draft: CaptureDraft) -> None:
        with self._lock:
            self._entries[user_id] = (draft, time.monotonic())

    def get(self, user_id: str) -> CaptureDraft | None:
        with self._lock:
            entry = self._entries.get(user_id)
            if entry is None:
                return None
            draft, stored_at = entry
            if time.monotonic() - stored_at > self.ttl_seconds:
                del self._entries[user_id]
                return None
            return draft

    def pop(self, user_id: str) -> CaptureDraft | None:
        with self._lock:
            entry = self._entries.pop(user_id, None)
        return entry[0] if entry is not None else None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


pending_capture_store = PendingCaptureStore()


def classify_category(text: str) -> str:
    lowered = f" {text.lower()} "
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


DESCRIPTION_STRIP_PHRASES = re.compile(r"\b(?:forked\s+out|shelled\s+out)\b", re.IGNORECASE)

DESCRIPTION_STRIP_TOKENS = frozenset(
    {
        # spend verbs / transport verbs
        "spent", "spend", "spends", "paid", "pays", "pay", "bought", "buy", "buys",
        "purchased", "purchase", "purchases", "took", "take", "takes", "used",
        "got", "getting", "costing", "cost", "costs", "priced",
        "booked", "book", "books", "reserved", "reserve", "reservation",
        # pronouns / auxiliaries / fillers
        "i", "we", "you", "they", "he", "she", "it", "me", "him", "them", "us",
        "my", "our", "your", "their", "his", "her", "have", "has", "had", "just",
        "about", "around", "roughly", "approximately", "approx", "some", "this",
        "that", "these", "those", "was", "were", "am", "is", "are", "for", "on",
        "at", "in", "and", "then", "also", "a", "an", "the", "to", "from", "with",
        "home", "back",
        # currency / money words
        "dollars", "dollar", "sgd", "cents", "cent",
        # time expressions
        "today", "yesterday", "tomorrow", "ago", "day", "days", "week", "weeks",
        "before",
        "month", "months", "year", "years", "last", "next", "past",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
        "jan", "january", "feb", "february", "mar", "march", "apr", "april", "may",
        "jun", "june", "jul", "july", "aug", "august", "sep", "sept", "september",
        "oct", "october", "nov", "november", "dec", "december",
    }
)

AMOUNT_TOKEN_PATTERN = re.compile(
    r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?$|^[${]|(?:\d|s)\$$|\d(?:st|nd|rd|th)$",
    re.IGNORECASE,
)


def _clean_description(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().strip(".,!?;:")
    cleaned = re.sub(r"^(?:on|for)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:on|for)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


BRAND_DISPLAY_NAMES = {
    "mrt": "MRT",
    "grab": "Grab",
    "singtel": "Singtel",
    "starhub": "StarHub",
    "hdb": "HDB",
    "cpf": "CPF",
}


def _extract_description(text: str, *, drop_bare_numbers: bool) -> str:
    text = DESCRIPTION_STRIP_PHRASES.sub(" ", text)
    text = re.sub(r"[.!?,;:]", " ", text)
    kept = []
    for token in re.sub(r"\s+", " ", text).strip().split(" "):
        if not token:
            continue
        lowered = token.lower().strip("'\"")
        if not lowered or lowered in DESCRIPTION_STRIP_TOKENS:
            continue
        if lowered in {"s$", "sgd"}:
            continue
        if AMOUNT_TOKEN_PATTERN.match(token):
            continue
        if drop_bare_numbers and token.isdigit():
            continue
        brand = BRAND_DISPLAY_NAMES.get(lowered)
        kept.append(brand if brand is not None else token.capitalize())
    return " ".join(kept).strip()


def parse_spending_statement(message: str) -> CaptureDraft | None:
    text = re.sub(r"\s+", " ", message).strip()
    if not text or text.endswith("?"):
        return None
    first_word = text.split(" ", 1)[0].lower().strip(".,!?;:")
    if first_word in QUESTION_PREFIXES:
        return None

    verb_match = SPEND_VERB_PATTERN.search(text)
    search_from = verb_match.end() if verb_match is not None else 0
    amount_match: re.Match[str] | None = None
    amount_value: str | None = None
    amount_was_bare = False
    if verb_match is None:
        amount_match = LEADING_AMOUNT_PATTERN.match(text)
        if amount_match is not None:
            amount_value = amount_match.group(1)
    else:
        marked = MARKED_AMOUNT_PATTERN.search(text, search_from)
        if marked is not None:
            amount_match = marked
            amount_value = marked.group(1) or marked.group(2)
        else:
            amount_match = BARE_AMOUNT_PATTERN.search(text, search_from)
            if amount_match is not None:
                amount_value = amount_match.group(0)
                amount_was_bare = True
    if amount_match is None or amount_value is None:
        return None
    try:
        amount = float(amount_value.replace(",", "."))
    except ValueError:
        return None
    if amount <= 0:
        return None

    description_text = (
        text[: amount_match.start()] + " " + text[amount_match.end():]
    )
    description_text = INLINE_DATE_PATTERN.sub(" ", description_text)
    description = (
        _extract_description(description_text, drop_bare_numbers=amount_was_bare)
        or _clean_description(description_text)
    )
    if not description:
        description = "expense"

    return CaptureDraft(
        amount=amount,
        description=description,
        category=classify_category(description),
        booking=BOOKING_PATTERN.search(text) is not None,
    )


def _validate_calendar_date(
    year: int, month: int, day: int, *, allow_future: bool = False
) -> tuple[date | None, bool]:
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None, False
    if candidate > _today():
        if allow_future:
            return candidate, False
        return None, True
    return candidate, False


def _resolve_weekday(name: str) -> date:
    target = WEEKDAY_NAMES[name.lower()]
    delta = (_today().weekday() - target) % 7
    return _today() - timedelta(days=delta or 7)


def _parse_date_token(
    token: str, *, allow_future: bool = False
) -> tuple[date | None, bool]:
    token = re.sub(r"\s+", " ", token).strip().lower()
    if not token or len(token) > 40:
        return None, False
    if re.search(r"\b(?:next|tomorrow)\b", token):
        return None, False
    if token in {
        "day before yesterday",
        "the day before yesterday",
        "the day before",
        "day before",
    }:
        return _today() - timedelta(days=2), False
    changed = True
    while changed:
        changed = False
        for filler in ("it was ", "on ", "the ", "it happened "):
            if token.startswith(filler):
                token = token[len(filler):]
                changed = True
                break
    if not token:
        return None, False
    if token == "today":
        return _today(), False
    if token == "yesterday":
        return _today() - timedelta(days=1), False
    match = re.fullmatch(r"(?:a|one|(\d{1,3}))\s+days?\s+ago", token)
    if match is not None:
        days = 1 if match.group(1) is None else int(match.group(1))
        return _today() - timedelta(days=days), False
    if token in WEEKDAY_NAMES:
        return _resolve_weekday(token), False
    match = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)", token)
    if match is not None:
        resolved, saw_future = _validate_calendar_date(
            _today().year, _today().month, int(match.group(1)), allow_future=allow_future
        )
        return resolved, saw_future
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", token)
    if match is not None:
        day, month = int(match.group(1)), int(match.group(2))
        if match.group(3) is not None:
            year = int(match.group(3))
            if year < 100:
                year += 2000
            return _validate_calendar_date(year, month, day, allow_future=allow_future)
        resolved, saw_future = _validate_calendar_date(
            _today().year, month, day, allow_future=allow_future
        )
        if resolved is None and saw_future:
            resolved, _ = _validate_calendar_date(_today().year - 1, month, day)
            return resolved, resolved is None
        return resolved, saw_future
    match = re.fullmatch(
        rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH_ALTERNATIVES})(?:\s+(\d{{2}}|\d{{4}}))?"
        rf"|({MONTH_ALTERNATIVES})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(\d{{2}}|\d{{4}}))?",
        token,
    )
    if match is not None:
        if match.group(1) is not None:
            day, month = int(match.group(1)), MONTH_NAMES[match.group(2)]
            year_part = match.group(3)
        else:
            month, day = MONTH_NAMES[match.group(4)], int(match.group(5))
            year_part = match.group(6)
        if year_part is not None:
            year = int(year_part)
            if year < 100:
                year += 2000
            return _validate_calendar_date(year, month, day, allow_future=allow_future)
        resolved, saw_future = _validate_calendar_date(
            _today().year, month, day, allow_future=allow_future
        )
        if resolved is None and saw_future:
            resolved, _ = _validate_calendar_date(_today().year - 1, month, day)
            return resolved, resolved is None
        return resolved, saw_future
    return None, False


def parse_date_expression(message: str, *, allow_future: bool = False) -> date | None:
    resolved, _ = _parse_date_token(message, allow_future=allow_future)
    return resolved


def extract_date_from_text(message: str, *, allow_future: bool = False) -> date | None:
    for match in INLINE_DATE_PATTERN.finditer(message):
        resolved, _ = _parse_date_token(match.group(0), allow_future=allow_future)
        if resolved is not None:
            return resolved
    return None


def mentions_future_date(message: str) -> bool:
    standalone, saw_future = _parse_date_token(message)
    if standalone is not None:
        return False
    if saw_future:
        return True
    for match in INLINE_DATE_PATTERN.finditer(message):
        _, token_future = _parse_date_token(match.group(0))
        if token_future:
            return True
    return False


def is_cancel_message(message: str) -> bool:
    return bool(CANCEL_PATTERN.fullmatch(message.strip().rstrip(".!")))


def _local_reply(session_id: str, answer: str) -> CoachResponse:
    audit: dict[str, Any] = {"source": "transaction_capture"}
    return CoachResponse(
        session_id=session_id,
        selected_agents=[],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit=audit,
    )


def _ask_date_reply(session_id: str, draft: CaptureDraft) -> CoachResponse:
    return _local_reply(
        session_id,
        f"Got it — SGD {draft.amount:.2f} for {draft.description}. "
        "When did you spend it? You can say 'yesterday', 'today', or a date like 21/9.",
    )


def _saved_reply(session_id: str, draft: CaptureDraft, when: date) -> CoachResponse:
    formatted = f"{when.day} {when.strftime('%b %Y')}"
    return _local_reply(
        session_id,
        f"Saved: {draft.description} for SGD {draft.amount:.2f} on {formatted} "
        f"under {draft.category.capitalize()}.",
    )


def handle_transaction_capture(session: Session, request: CoachRequest) -> CoachResponse | None:
    user_id = request.user_id
    session_id = request.session_id
    message = request.message

    def save(draft: CaptureDraft, when: date) -> CoachResponse:
        try:
            SQLAlchemyTransactionRepository(session).create(
                user_id,
                TransactionCreate(
                    description=draft.description,
                    category=draft.category,
                    amount=MoneyAmount(amount=draft.amount),
                    occurred_on=when,
                ),
            )
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            pending_capture_store.put(user_id, draft)
            return _local_reply(
                session_id, "Sorry, I couldn't save that transaction. Please try again."
            )
        log_event(
            "transaction.added",
            source="coach_capture",
            category=draft.category,
        )
        reply = _saved_reply(session_id, draft, when)
        from app.services.budget_alert import category_overage_note

        note = category_overage_note(session, user_id, when.replace(day=1), draft.category)
        if note:
            reply = reply.model_copy(update={"answer": reply.answer + note})
        return reply

    pending = pending_capture_store.get(user_id)
    if pending is not None:
        if is_cancel_message(message):
            pending_capture_store.pop(user_id)
            return _local_reply(
                session_id, "OK, I've dropped that transaction. Nothing was saved."
            )
        resolved = parse_date_expression(message, allow_future=pending.booking)
        if resolved is not None:
            pending_capture_store.pop(user_id)
            return save(pending, resolved)
        if mentions_future_date(message) and not pending.booking:
            return _local_reply(
                session_id,
                "That date is in the future — when did you spend it?",
            )
        replacement = parse_spending_statement(message)
        if replacement is not None:
            inline = extract_date_from_text(message, allow_future=replacement.booking)
            if inline is not None:
                pending_capture_store.pop(user_id)
                return save(replacement, inline)
            pending_capture_store.put(user_id, replacement)
            return _ask_date_reply(session_id, replacement)
        pending_capture_store.pop(user_id)
        return None

    draft = parse_spending_statement(message)
    if draft is None:
        return None
    inline = extract_date_from_text(message, allow_future=draft.booking)
    if inline is not None:
        return save(draft, inline)
    pending_capture_store.put(user_id, draft)
    return _ask_date_reply(session_id, draft)
