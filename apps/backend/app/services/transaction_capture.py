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
    when: date | None = None


class PendingCaptureStore:
    def __init__(self, ttl_seconds: float = PENDING_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[list[CaptureDraft], float]] = {}

    def put(self, user_id: str, draft: CaptureDraft) -> None:
        self.put_queue(user_id, [draft])

    def put_queue(self, user_id: str, drafts: list[CaptureDraft]) -> None:
        with self._lock:
            if drafts:
                self._entries[user_id] = (list(drafts), time.monotonic())
            else:
                self._entries.pop(user_id, None)

    def _live(self, user_id: str) -> list[CaptureDraft] | None:
        entry = self._entries.get(user_id)
        if entry is None:
            return None
        drafts, stored_at = entry
        if time.monotonic() - stored_at > self.ttl_seconds:
            del self._entries[user_id]
            return None
        return drafts or None

    def get(self, user_id: str) -> CaptureDraft | None:
        with self._lock:
            drafts = self._live(user_id)
            return drafts[0] if drafts else None

    def peek_all(self, user_id: str) -> list[CaptureDraft]:
        with self._lock:
            drafts = self._live(user_id)
            return list(drafts) if drafts else []

    def replace(self, user_id: str, drafts: list[CaptureDraft]) -> None:
        with self._lock:
            stored_at = self._entries[user_id][1] if user_id in self._entries else time.monotonic()
            if drafts:
                self._entries[user_id] = (list(drafts), stored_at)
            else:
                self._entries.pop(user_id, None)

    def drop(self, user_id: str) -> list[CaptureDraft]:
        with self._lock:
            drafts = self._live(user_id)
            self._entries.pop(user_id, None)
            return list(drafts) if drafts else []

    def pop(self, user_id: str) -> CaptureDraft | None:
        with self._lock:
            drafts = self._live(user_id)
            if not drafts:
                self._entries.pop(user_id, None)
                return None
            first = drafts.pop(0)
            if drafts:
                self._entries[user_id] = (drafts, self._entries[user_id][1])
            else:
                del self._entries[user_id]
            return first

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
        "add", "added", "record", "recorded", "log", "logged", "enter", "here",
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


MEAL_REWRITE_PATTERN = re.compile(
    r"\bon\s+([a-z0-9][a-z0-9 ]*?)\s+(?:for\s+)?(?:\S*'s\s+|'s\s+)?"
    r"(lunch|dinner|breakfast|brunch|supper|snack)\b",
    re.IGNORECASE,
)


def _titlecase_phrase(phrase: str) -> str:
    def cap_word(word: str) -> str:
        for index, character in enumerate(word):
            if character.isalpha():
                return word[:index] + character.upper() + word[index + 1:]
        return word

    return " ".join(cap_word(word) for word in phrase.split())


def _extract_description(text: str, *, drop_bare_numbers: bool) -> str:
    text = MEAL_REWRITE_PATTERN.sub(
        lambda m: f"{m.group(2).capitalize()} ({_titlecase_phrase(m.group(1).strip())})", text
    )
    text = DESCRIPTION_STRIP_PHRASES.sub(" ", text)
    text = re.sub(r"[.!?,;:]", " ", text)
    kept = []
    for token in re.sub(r"\s+", " ", text).strip().split(" "):
        if not token:
            continue
        lowered = token.lower().strip("'\"")
        if not lowered or lowered in DESCRIPTION_STRIP_TOKENS:
            continue
        if token.startswith("'"):
            continue
        if lowered in {"s$", "sgd"}:
            continue
        if AMOUNT_TOKEN_PATTERN.match(token):
            continue
        if drop_bare_numbers and token.isdigit():
            continue
        brand = BRAND_DISPLAY_NAMES.get(lowered)
        if brand is not None:
            kept.append(brand)
        elif token[:1].isalpha():
            kept.append(token[0].upper() + token[1:])
        else:
            kept.append(token)
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


BATCH_HEADER_PATTERN = re.compile(
    r"\b(?:add|record|log|enter|input)\b[^.:;]*\b(?:expense|expenses|transaction|transactions|"
    r"spending|purchase|purchases)\b",
    re.IGNORECASE,
)


def _split_segments(message: str) -> list[str]:
    raw_lines = re.split(r"[\r\n]+|(?<=:)\s+", message)
    segments: list[str] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        segments.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", line) if part.strip())
    return segments


def parse_batch(message: str) -> list[CaptureDraft] | None:
    segments = _split_segments(message)
    if len(segments) < 2:
        return None
    header_present = any(
        BATCH_HEADER_PATTERN.search(segment) and parse_spending_statement(segment) is None
        for segment in segments
    )
    drafts: list[CaptureDraft] = []
    for segment in segments:
        draft = parse_spending_statement(segment)
        if draft is None:
            continue
        draft.when = extract_date_from_text(segment, allow_future=draft.booking)
        drafts.append(draft)
    if len(drafts) >= 2:
        return drafts
    if header_present and drafts:
        return drafts
    return None


def _ask_queue_reply(session_id: str, next_draft: CaptureDraft, saved_parts: list[str]) -> CoachResponse:
    prefix = " ".join(saved_parts)
    question = (
        f"When did you spend the {next_draft.description.lower()}? "
        "You can say 'yesterday', 'today', or a date like 21/9."
    )
    answer = f"{prefix} {question}" if prefix else question
    return _local_reply(session_id, answer)


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


def handle_transaction_capture(session: Session, request: CoachRequest) -> CoachResponse | None:
    user_id = request.user_id
    session_id = request.session_id
    message = request.message

    def save_one(draft: CaptureDraft, when: date) -> str:
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
            return "Sorry, I couldn't save that transaction. Please try again."
        log_event(
            "transaction.added",
            source="coach_capture",
            category=draft.category,
        )
        formatted = f"{when.day} {when.strftime('%b %Y')}"
        part = (
            f"{draft.description} for SGD {draft.amount:.2f} on {formatted} "
            f"under {draft.category.capitalize()}"
        )
        from app.services.budget_alert import category_overage_note

        note = category_overage_note(session, user_id, when.replace(day=1), draft.category)
        if note:
            part = part + " " + note.strip()
        return part

    def finalize(parts: list[str]) -> str:
        body = "; ".join(parts)
        return f"Saved: {body}" + ("" if body.endswith((".", "!")) else ".")

    def save_list(drafts: list[CaptureDraft], dates: list[date]) -> str:
        parts = [save_one(draft, when) for draft, when in zip(drafts, dates, strict=True)]
        return finalize(parts)

    pending = pending_capture_store.peek_all(user_id)
    if pending:
        if is_cancel_message(message):
            dropped = pending_capture_store.drop(user_id)
            if len(dropped) == 1:
                return _local_reply(
                    session_id, "OK, I've dropped that transaction. Nothing was saved."
                )
            return _local_reply(
                session_id,
                f"OK, I've dropped {len(dropped)} pending transactions. Nothing was saved.",
            )
        allow_future = any(draft.booking for draft in pending)
        resolved = parse_date_expression(message, allow_future=allow_future)
        if resolved is not None:
            drafts = pending_capture_store.drop(user_id)
            target = drafts[0]
            remainder = drafts[1:]
            saved_part = save_one(target, resolved)
            failed = saved_part.startswith("Sorry")
            if failed:
                pending_capture_store.put_queue(user_id, drafts)
                return _local_reply(session_id, saved_part)
            if remainder:
                pending_capture_store.put_queue(user_id, remainder)
                return _ask_queue_reply(session_id, remainder[0], [saved_part])
            return _local_reply(session_id, finalize([saved_part]))
        if mentions_future_date(message) and not allow_future:
            return _local_reply(
                session_id,
                "That date is in the future — when did you spend it?",
            )
        batch = parse_batch(message)
        if batch is not None:
            pending_capture_store.drop(user_id)
            return _handle_parsed_batch(session, session_id, user_id, batch, save_list, save_one)
        replacement = parse_spending_statement(message)
        if replacement is not None:
            pending_capture_store.drop(user_id)
            inline = extract_date_from_text(message, allow_future=replacement.booking)
            if inline is not None:
                saved_part = save_one(replacement, inline)
                answer = saved_part if saved_part.startswith("Sorry") else finalize([saved_part])
                return _local_reply(session_id, answer)
            pending_capture_store.put(user_id, replacement)
            return _ask_date_reply(session_id, replacement)
        pending_capture_store.drop(user_id)
        return None

    batch = parse_batch(message)
    if batch is not None:
        return _handle_parsed_batch(session, session_id, user_id, batch, save_list, save_one)

    draft = parse_spending_statement(message)
    if draft is None:
        return None
    inline = extract_date_from_text(message, allow_future=draft.booking)
    if inline is not None:
        saved_part = save_one(draft, inline)
        answer = saved_part if saved_part.startswith("Sorry") else finalize([saved_part])
        return _local_reply(session_id, answer)
    pending_capture_store.put(user_id, draft)
    return _ask_date_reply(session_id, draft)


def _handle_parsed_batch(
    session: Session,
    session_id: str,
    user_id: str,
    batch: list[CaptureDraft],
    save_list,
    save_one,
) -> CoachResponse:
    dated = [draft for draft in batch if draft.when is not None]
    undated = [draft for draft in batch if draft.when is None]
    if dated:
        summary = save_list(dated, [draft.when for draft in dated])  # type: ignore[arg-type]
    else:
        summary = ""
    if undated:
        pending_capture_store.put_queue(user_id, undated)
        return _ask_queue_reply(session_id, undated[0], [summary] if summary else [])
    return _local_reply(session_id, summary)
