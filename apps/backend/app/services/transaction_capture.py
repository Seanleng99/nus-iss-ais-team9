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
from app.domain.schemas import ApplicationMoneyAmount, CoachRequest, CoachResponse
from app.infrastructure.repositories import SQLAlchemyTransactionRepository

AMEND_PREFIX_PATTERN = re.compile(
    r"^\s*(?:oh\s+)?(?:sorry|oops|wait|hold\s+on)[,!.]?\s+"
    r"|^\s*(?:actually|correction)[,!]?\s+"
    r"|^\s*(?:make\s+it|change\s+it\s+to|it\s+should\s+be|no[,]?\s+it(?:'s| is))\b",
    re.IGNORECASE,
)

AMEND_AMOUNT_PATTERN = re.compile(
    r"^\s*(?:s?\$\s*|sgd\s+)?(\d{1,7}(?:[.,]\d{1,2})?)\s*(?:sgd|dollars?|s\$|bucks?)?$",
    re.IGNORECASE,
)

AMEND_FILLER_TOKENS = frozenset(
    {
        "its", "it", "it's", "it is", "is", "was", "the", "amount", "price", "total",
        "make", "change", "correct", "corrected", "should", "be", "to", "not",
        "cost", "costs", "costed", "paid", "pay", "instead", "rather", "said",
        "oops", "sorry", "actually", "correction", "misread", "mistake",
        "that", "this", "one",
    }
)

EDIT_DIRECTIVE_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:edit|change|update|correct|amend)\b"
    r"\s+(?P<target>[^.!?]{1,120}?)"
    r"\s+(?:to|at|as)\s+(?:s?\$\s*|sgd\s*)?(?P<amount>\d{1,7}(?:[.,]\d{1,2})?)\s*"
    r"(?:sgd|dollars?|s\$|bucks?)?\s*[.!]?$",
    re.IGNORECASE,
)

EDIT_REQUEST_PATTERN = re.compile(
    r"\b(?:edit|change|update|correct|amend)\b"
    r"\s+(?P<target>[^.!?]{1,120}?)"
    r"\s+(?:to|at|as)\s+(?:s?\$\s*|sgd\s*)?(?P<amount>\d{1,7}(?:[.,]\d{1,2})?)\s*"
    r"(?:sgd|dollars?|s\$|bucks?)?\s*[.!?]*$",
    re.IGNORECASE,
)

TRANSACTION_NAME_PATTERN = re.compile(
    r"\btransaction\s+(?:for|called|named)\s+(?P<name>[a-z0-9' ]{2,80})(?:\s*[.!?]|$)",
    re.IGNORECASE,
)

DELETE_DIRECTIVE_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:delete|remove)\b\s+(?P<target>[^.!?]{1,120}?)[.!?]*$",
    re.IGNORECASE,
)

DELETE_REQUEST_PATTERN = re.compile(
    r"\b(?:delete|remove)\b\s+(?P<target>[^.!?]{1,120}?)[.!?]*$",
    re.IGNORECASE,
)

EDIT_META_WORDS = frozenset(
    {
        "transaction", "transactions", "spending", "spend", "expense", "expenses",
        "amount", "amounts", "price", "cost", "costs", "total", "purchase",
        "purchases", "entry", "entries", "record", "records", "receipt", "value",
    }
)

EDIT_CONFIRM_PATTERN = re.compile(
    r"^(?:yes|yeah|yep|yup|confirm|confirmed|ok|okay|do it|go ahead|save it)$",
    re.IGNORECASE,
)

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
    r"\b(?:spent|spends|spend|paid|pays|pay|bought|buys|purchased|purchases|took|take|takes|"
    r"booked|book|books|reserved|reserve|forked\s+out|shelled\s+out|"
    r"gave|give|gives|sent|send|sends|mailed|mail|settled|settle|donated|donate|"
    r"treated|treat|treats|grabbed|charged|charge|charges|cost|costs|transacted|transact)\b",
    re.IGNORECASE,
)

DETAILS_VERB_PATTERN = re.compile(
    r"\b(?:spent|spend|paid|pays|bought|buys|purchased|purchases|booked|book|books|"
    r"reserved|reserve)\b",
    re.IGNORECASE,
)

DETAILS_WEAK_VERB_PATTERN = re.compile(
    r"\b(?:got|getting|picked\s+up|took|take|takes)\b", re.IGNORECASE
)

EXPENSE_NOUN_PATTERN = re.compile(
    r"\b(?:ticket|tickets|bill|bills|fare|fares|fee|fees|groceries|flight|hotel|"
    r"rent|insurance|subscription|phone|laptop|bag|bags|shoes|shirt|watch|gift|gifts)\b",
    re.IGNORECASE,
)

DETAILS_OPINION_PATTERN = re.compile(
    r"\b(?:is|are|was|were|be|been|want|wanted|like|liked|think|thought|should|"
    r"need|needed|prefer|broken|better|reduce|cut|save|"
    r"question|budget|budgeting|afford)\b",
    re.IGNORECASE,
)

BOOKING_PATTERN = re.compile(r"\b(?:booked|book|books|reserved|reserve|reservation)\b", re.IGNORECASE)

RECURRING_PATTERN = re.compile(
    r"\b(?:recurring|monthly|yearly|annual(?:ly)?|weekly|subscription|"
    r"every\s+(?:month|week|year)|each\s+month|per\s+month)\b",
    re.IGNORECASE,
)

POLITE_ADD_PREFIX_PATTERN = re.compile(
    r"^(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:help\s+me\s+)?",
    re.IGNORECASE,
)
CAPTURE_DIRECTIVE_PATTERN = re.compile(
    r"^(?:please\s+|kindly\s+)?(?:add|record|log|enter|store)\b",
    re.IGNORECASE,
)
CAPTURE_OBJECT_PATTERN = re.compile(
    r"^(?:a|an|the|this|that)?\s*(?:new\s+)?(?:transaction|expense|expenditure|spending)\b\s*",
    re.IGNORECASE,
)

MARKED_AMOUNT_PATTERN = re.compile(
    r"(?:(?:[$]|s\$)\s*|sgd\s+)(\d{1,7}(?:[.,]\d{1,2})?)"
    r"|(\d{1,7}(?:[.,]\d{1,2})?)\s*(?:(?:sgd|dollars?|s\$)\b|[块元])",
    re.IGNORECASE,
)
BARE_AMOUNT_PATTERN = re.compile(
    r"(?<![\d/.,])\d{1,7}(?:[.,]\d{1,2})?(?![\d/])"
)
AMOUNT_MULTIPLIER_PATTERN = re.compile(
    r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:x|×|\*)\s*(\d+(?:\.\d+)?)(?![\d.])"
)
K_MULTIPLIER_PATTERN = re.compile(r"(?<![\d.])(\d{1,6}(?:\.\d+)?)k(?![a-z0-9])", re.IGNORECASE)
THOUSANDS_COMMA_PATTERN = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
LEDGER_NEGATIVE_PATTERN = re.compile(r"(?<![\d.,-])-(?=\d)")

INCOME_GUARD_PATTERN = re.compile(
    r"\b(?:budget|budgeting|income|salary|wages?|earnings?|owe|owing|owed|debt|"
    r"savings|afford|lend|lent)\b",
    re.IGNORECASE,
)

UNIT_GUARD_WORDS = frozenset(
    {
        "degree", "degrees", "°", "year", "years", "old", "age", "ages",
        "week", "weeks", "day", "days", "hour", "hours", "minute", "minutes",
        "mins", "second", "seconds", "month", "months", "kg", "km", "cm", "mm",
        "people", "person", "pax", "percent", "%", "am", "pm", "o'clock",
    }
)

COPULA_AMOUNT_PATTERN = re.compile(
    r"\b(?:was|were|is|are)\s+(?:s?\$\s*|sgd\s+)?(\d{1,7}(?:[.,]\d{1,2})?)(?![\d/])",
    re.IGNORECASE,
)

AMOUNT_FOLLOWUP_PATTERN = re.compile(
    r"^(?:(?:it\s+)?(?:was|cost|costs|paid|for)\s+)?"
    r"(?:about|around|roughly|approximately|approx)?\s*"
    r"(?:s?\$\s*|sgd\s*)?(\d{1,7}(?:[.,]\d{1,2})?)\s*"
    r"(?:sgd|dollars?|s\$|bucks?)?$",
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
    rf"|\b(?:the\s+)?\d{{1,2}}(?:st|nd|rd|th)\b(?!\s+of\s+|\s+(?:{MONTH_ALTERNATIVES})\b)"
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
                   "scoot", "rideshare", "flight", "airticket", "air ticket")),
    ("housing", ("rent", "mortgage", "maintenance fee", "service charge", "condo", "hdb")),
    ("utilities", ("utilit", "electricity", "power bill", "sproupit", "water bill",
                   "gas bill", "internet", "broadband",
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
    need_amount: bool = False
    recurring: bool = False


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


@dataclass
class LastSavedRecord:
    transaction_id: Any
    description: str
    category: str
    amount: float
    when: date
    recurring: bool = False


class LastSavedStore:
    def __init__(self, ttl_seconds: float = PENDING_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[LastSavedRecord, float]] = {}

    def remember(self, user_id: str, record: LastSavedRecord) -> None:
        with self._lock:
            self._entries[user_id] = (record, time.monotonic())

    def get(self, user_id: str) -> LastSavedRecord | None:
        with self._lock:
            entry = self._entries.get(user_id)
            if entry is None:
                return None
            record, stored_at = entry
            if time.monotonic() - stored_at > self.ttl_seconds:
                del self._entries[user_id]
                return None
            return record

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


last_saved_store = LastSavedStore()


@dataclass
class EditCandidate:
    transaction_id: Any
    description: str
    category: str
    amount: float
    when: date
    recurring: bool = False


@dataclass
class PendingEdit:
    new_amount: float
    candidates: list[EditCandidate]
    candidate: EditCandidate | None
    op: str = "edit"


class PendingEditStore:
    def __init__(self, ttl_seconds: float = PENDING_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[PendingEdit, float]] = {}

    def put(self, user_id: str, pending: PendingEdit) -> None:
        with self._lock:
            self._entries[user_id] = (pending, time.monotonic())

    def get(self, user_id: str) -> PendingEdit | None:
        with self._lock:
            entry = self._entries.get(user_id)
            if entry is None:
                return None
            pending, stored_at = entry
            if time.monotonic() - stored_at > self.ttl_seconds:
                del self._entries[user_id]
                return None
            return pending

    def drop(self, user_id: str) -> None:
        with self._lock:
            self._entries.pop(user_id, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


pending_edit_store = PendingEditStore()

EDIT_STOP_WORDS = EDIT_META_WORDS | frozenset(
    {
        "my", "the", "a", "an", "this", "that", "these", "those", "it", "its",
        "for", "of", "to", "is", "was", "have", "has", "there", "one",
        "me", "you", "can", "could", "would", "will", "help", "please",
        "delete", "remove", "edit", "change", "update", "on", "at", "in", "did",
        "made", "make", "able",
    }
)


def _edit_keywords(target: str) -> list[str]:
    words = [
        word
        for word in re.sub(r"[^a-z0-9 ]", " ", target.lower()).split()
        if word not in EDIT_STOP_WORDS
    ]
    return words


DAY_MONTH_NAME_FILTER_PATTERN = re.compile(
    rf"\b(?:the\s+)?\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTH_ALTERNATIVES})\b(?:\s+\d{{2,4}})?",
    re.IGNORECASE,
)


def _split_name_and_date_filter(target: str) -> tuple[list[str], date | None]:
    match = DAY_MONTH_NAME_FILTER_PATTERN.search(target)
    if match is not None:
        parsed, _ = _parse_date_token(match.group(0), allow_future=True)
        if parsed is not None:
            target = target[: match.start()] + " " + target[match.end():]
            return _edit_keywords(target), parsed
    when_filter = extract_date_from_text(target, allow_future=True)
    if when_filter is not None:
        target = INLINE_DATE_PATTERN.sub(" ", target)
    return _edit_keywords(target), when_filter


def classify_category(text: str) -> str:
    lowered = f" {text.lower()} "
    for category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


DESCRIPTION_STRIP_PHRASES = re.compile(
    r"\b(?:forked\s+out|shelled\s+out)\b|花了|化了", re.IGNORECASE
)

DESCRIPTION_STRIP_TOKENS = frozenset(
    {
        # spend verbs / transport verbs
        "spent", "spend", "spends", "paid", "pays", "pay", "bought", "buy", "buys",
        "purchased", "purchase", "purchases", "took", "take", "takes", "used",
        "got", "getting", "costing", "cost", "costs", "priced",
        "gave", "give", "gives", "sent", "send", "sends", "mailed", "mail",
        "settled", "settle", "donated", "donate", "treated", "treat", "treats",
        "grabbed", "charged", "charge", "charges", "transacted", "transact", "transacts",
        "grand", "out",
        "add", "added", "record", "recorded", "log", "logged", "enter", "here",
        "store", "stored", "please", "kindly",
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
        "night",
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
        lowered = token.lower().strip("-'\"")
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
    if INCOME_GUARD_PATTERN.search(text):
        return None
    polite = POLITE_ADD_PREFIX_PATTERN.match(text)
    if polite is not None:
        remainder = text[polite.end():].strip()
        if CAPTURE_DIRECTIVE_PATTERN.match(remainder):
            text = remainder
    directive = CAPTURE_DIRECTIVE_PATTERN.match(text)
    if directive is not None and len(text) > directive.end():
        text = text[directive.end():].strip()
        object_prefix = CAPTURE_OBJECT_PATTERN.match(text)
        if object_prefix is not None and len(text) > object_prefix.end():
            text = text[object_prefix.end():].strip()
    first_word = text.split(" ", 1)[0].lower().strip(".,!?;:")
    if first_word in QUESTION_PREFIXES:
        return None

    multiplier = AMOUNT_MULTIPLIER_PATTERN.search(text)
    if multiplier is not None:
        try:
            amount = float(multiplier.group(1).replace(",", ".")) * float(multiplier.group(2))
        except ValueError:
            amount = 0.0
        if amount > 0:
            rest = text[: multiplier.start()] + " " + text[multiplier.end():]
            return _draft_from_rest(rest, amount, text)

    text = THOUSANDS_COMMA_PATTERN.sub("", text)
    thousands_k = K_MULTIPLIER_PATTERN.search(text)
    if thousands_k is not None:
        try:
            amount = float(thousands_k.group(1)) * 1000
        except ValueError:
            amount = 0.0
        if amount > 0:
            rest = text[: thousands_k.start()] + " " + text[thousands_k.end():]
            return _draft_from_rest(rest, amount, text)
    text = LEDGER_NEGATIVE_PATTERN.sub(" ", text)

    verb_match = SPEND_VERB_PATTERN.search(text)
    search_from = verb_match.end() if verb_match is not None else 0
    amount_match: re.Match[str] | None = None
    amount_value: str | None = None
    amount_was_bare = False
    description_before_amount_only = False
    if verb_match is None:
        amount_match = MARKED_AMOUNT_PATTERN.search(text)
        if amount_match is not None:
            amount_value = amount_match.group(1) or amount_match.group(2)
        else:
            copula = COPULA_AMOUNT_PATTERN.search(text)
            if copula is not None and _passes_unit_guard(copula, text):
                amount_match = copula
                amount_value = copula.group(1) or copula.group(2)
                description_before_amount_only = True
            else:
                bare = _bare_amount_without_verb(text)
                if bare is not None:
                    stripped_text, bare_match = bare
                    text = stripped_text
                    amount_match = bare_match
                    amount_value = bare_match.group(0)
                    amount_was_bare = True
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

    if description_before_amount_only:
        description_text = text[: amount_match.start()]
    else:
        description_text = (
            text[: amount_match.start()] + " " + text[amount_match.end():]
        )
    return _draft_from_rest(description_text, amount, text, drop_bare=amount_was_bare)


def _draft_from_rest(
    description_text: str,
    amount: float,
    full_text: str,
    *,
    drop_bare: bool = True,
) -> CaptureDraft | None:
    description_text = INLINE_DATE_PATTERN.sub(" ", description_text)
    description = (
        _extract_description(description_text, drop_bare_numbers=drop_bare)
        or _clean_description(description_text)
    )
    if not description:
        description = "expense"
    return CaptureDraft(
        amount=amount,
        description=description,
        category=classify_category(description),
        booking=BOOKING_PATTERN.search(full_text) is not None,
        recurring=RECURRING_PATTERN.search(full_text) is not None,
    )


FILLER_LEADING_TOKENS = frozenset({"grand", "got", "get", "a", "an", "the"})
MAX_NO_VERB_TOKENS = 8
MAX_BARE_UNMARKED_AMOUNT = 9999.99

NO_VERB_GUARD_WORDS = frozenset(
    {
        "question", "code", "error", "errors", "issue", "issues", "number",
        "id", "uuid", "trace", "score", "version", "answer", "password",
        "token", "secret", "limit", "count", "port", "timestamp", "temperature",
    }
)


def _unit_guard_hit(match: re.Match[str], text: str) -> bool:
    if match.end() < len(text) and text[match.end()].isalpha():
        return True
    remainder = text[match.end():].strip().split(" ", 1)
    return bool(remainder) and remainder[0].lower().strip(".,!?;:") in UNIT_GUARD_WORDS


def _passes_unit_guard(match: re.Match[str], text: str) -> bool:
    return not _unit_guard_hit(match, text)


def _bare_amount_without_verb(
    text: str,
) -> tuple[str, re.Match[str]] | None:
    tokens = text.split(" ")
    leading = 0
    while (
        leading < len(tokens) - 1
        and tokens[leading].lower().strip(".,!?;:") in FILLER_LEADING_TOKENS
    ):
        leading += 1
    tokens = tokens[leading:]
    if len(tokens) > MAX_NO_VERB_TOKENS or len(tokens) < 2:
        return None
    stripped_text = " ".join(tokens)
    if BARE_AMOUNT_PATTERN.fullmatch(tokens[0]):
        match = BARE_AMOUNT_PATTERN.search(stripped_text)
        return (stripped_text, match) if match is not None and match.start() == 0 else None
    first = tokens[0].lower().strip(".,!?;:")
    if not first.isalpha() or first in DESCRIPTION_STRIP_TOKENS:
        return None
    if any(token.lower().strip(".,!?;:") in NO_VERB_GUARD_WORDS for token in tokens):
        return None
    match = BARE_AMOUNT_PATTERN.search(stripped_text)
    if match is None or _unit_guard_hit(match, stripped_text):
        return None
    try:
        value = float(match.group(0).replace(",", "."))
    except ValueError:
        return None
    if value > MAX_BARE_UNMARKED_AMOUNT:
        return None
    return stripped_text, match


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


def parse_amount_followup(message: str) -> float | None:
    match = AMOUNT_FOLLOWUP_PATTERN.match(re.sub(r"\s+", " ", message).strip())
    if match is None:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_spending_details(message: str) -> CaptureDraft | None:
    if MARKED_AMOUNT_PATTERN.search(message) or BARE_AMOUNT_PATTERN.search(message):
        return None
    for segment in _split_segments(message):
        if segment.endswith("?") or "?" in segment:
            continue
        lowered_segment = segment.lower()
        if re.search(r"\b(?:what|how|why|when)\b", lowered_segment):
            continue
        if re.search(r"\b(?:next|tomorrow)\b", lowered_segment):
            continue
        if DETAILS_OPINION_PATTERN.search(segment):
            continue
        first_word = segment.split(" ", 1)[0].lower().strip(".,!?;:")
        if first_word in QUESTION_PREFIXES:
            continue
        has_verb = DETAILS_VERB_PATTERN.search(segment) is not None
        has_noun = EXPENSE_NOUN_PATTERN.search(segment) is not None
        has_weak = DETAILS_WEAK_VERB_PATTERN.search(segment) is not None
        if not has_verb and not (has_noun and has_weak):
            continue
        when = extract_date_from_text(segment)
        description_text = INLINE_DATE_PATTERN.sub(" ", segment)
        description = _extract_description(description_text, drop_bare_numbers=True)
        if not description:
            continue
        return CaptureDraft(
            amount=0.0,
            description=description,
            category=classify_category(description),
            booking=BOOKING_PATTERN.search(segment) is not None,
            when=when,
            need_amount=True,
        )
    return None


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


def parse_last_saved_amendment(
    message: str,
) -> tuple[float | None, date | None] | None:
    prefix = AMEND_PREFIX_PATTERN.match(message)
    if prefix is None:
        return None
    remainder = message[prefix.end():].strip()
    if not remainder:
        return None
    when = extract_date_from_text(remainder)
    if when is not None:
        remainder = INLINE_DATE_PATTERN.sub(" ", remainder)
    tokens = [token for token in re.split(r"[^a-z0-9'.]+", remainder.lower()) if token]
    if not tokens:
        return (None, when) if when is not None else None
    meaningful = [token for token in tokens if token not in AMEND_FILLER_TOKENS]
    if not meaningful:
        return (None, when) if when is not None else None
    match = AMEND_AMOUNT_PATTERN.match(" ".join(meaningful))
    if match is None:
        return None
    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    if amount <= 0:
        return None
    return amount, when


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


def _split_and_items(segment: str) -> list[str]:
    parts = re.split(r"\s+and\s+", segment, flags=re.IGNORECASE)
    if len(parts) < 2:
        return [segment]
    if all(BARE_AMOUNT_PATTERN.search(part) for part in parts):
        return parts
    return [segment]


COMMA_ITEM_SEPARATOR = re.compile(r",\s+")


def _split_comma_items(segment: str) -> list[str]:
    parts = [part.strip() for part in COMMA_ITEM_SEPARATOR.split(segment) if part.strip()]
    if len(parts) < 2:
        return [segment]
    parts = [re.sub(r"^(?:and|also)\s+", "", part, flags=re.IGNORECASE) for part in parts]
    if all(BARE_AMOUNT_PATTERN.search(part) for part in parts):
        return parts
    return [segment]


def parse_batch(message: str) -> list[CaptureDraft] | None:
    raw_segments = _split_segments(message)
    segment_groups: list[list[str]] = []
    for segment in raw_segments:
        group: list[str] = []
        for part in _split_and_items(segment):
            for sub in _split_comma_items(part):
                group.extend(_split_and_items(sub))
        segment_groups.append(group)
    segments = [item for group in segment_groups for item in group]
    if len(segments) < 2:
        return None
    header_present = any(
        BATCH_HEADER_PATTERN.search(segment) and parse_spending_statement(segment) is None
        for segment in segments
    )
    drafts: list[CaptureDraft] = []
    header_dates: list[date] = []
    for group in segment_groups:
        group_drafts: list[CaptureDraft] = []
        for segment in group:
            draft = parse_spending_statement(segment)
            if draft is None:
                header_date = extract_date_from_text(segment)
                if (
                    header_date is not None
                    and MARKED_AMOUNT_PATTERN.search(segment) is None
                    and BARE_AMOUNT_PATTERN.search(segment) is None
                ):
                    header_dates.append(header_date)
                continue
            draft.when = extract_date_from_text(segment, allow_future=draft.booking)
            group_drafts.append(draft)
        if len(group_drafts) >= 2:
            shared = next((draft.when for draft in group_drafts if draft.when is not None), None)
            if shared is not None:
                for draft in group_drafts:
                    if draft.when is None:
                        draft.when = shared
        drafts.extend(group_drafts)
    if header_dates:
        for draft in drafts:
            if draft.when is None:
                draft.when = header_dates[0]
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
        selected_agents=["spending"],
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


def _ask_amount_reply(session_id: str, draft: CaptureDraft) -> CoachResponse:
    if draft.when is None:
        when_text = ""
    elif draft.when == _today():
        when_text = " today"
    else:
        when_text = f" on {draft.when.strftime('%d %b')}"
    return _local_reply(
        session_id,
        f"Got it — the {draft.description.lower()}{when_text}. "
        "How much did it cost? You can say for example 'about 25' or '$25'.",
    )


def handle_transaction_capture(session: Session, request: CoachRequest) -> CoachResponse | None:
    # New spending records and lookups now run through the AI-service capture
    # flow (transaction_staging). This handler keeps only named edit, delete
    # and last-saved amendment helpers.
    user_id = request.user_id
    session_id = request.session_id
    message = request.message

    def save_one(draft: CaptureDraft, when: date) -> str:
        try:
            record = SQLAlchemyTransactionRepository(session).create(
                user_id,
                TransactionCreate(
                    description=draft.description,
                    category=draft.category,
                    amount=ApplicationMoneyAmount(amount=draft.amount),
                    occurred_on=when,
                    recurring=draft.recurring,
                ),
            )
            session.commit()
            last_saved_store.remember(
                user_id,
                LastSavedRecord(
                    transaction_id=record.id,
                    description=draft.description,
                    category=draft.category,
                    amount=draft.amount,
                    when=when,
                    recurring=draft.recurring,
                ),
            )
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

    def save_list(drafts: list[CaptureDraft], dates: list[date]) -> str:
        parts = [save_one(draft, when) for draft, when in zip(drafts, dates, strict=True)]
        return _finalize(parts)

    pending_edit = pending_edit_store.get(user_id)
    if pending_edit is not None:
        if is_cancel_message(message):
            pending_edit_store.drop(user_id)
            if pending_edit.op == "delete":
                return _local_reply(
                    session_id, "OK, I've dropped that delete. Nothing was deleted."
                )
            return _local_reply(
                session_id, "OK, I've dropped that edit. Nothing was changed."
            )
        if EDIT_CONFIRM_PATTERN.fullmatch(message.strip().rstrip(".!")):
            if pending_edit.candidate is None:
                return _local_reply(
                    session_id,
                    "Which one did you mean? Mention its date, for example 'the 21 Sep one'.",
                )
            if pending_edit.op == "delete":
                return _apply_named_delete(session, session_id, user_id, pending_edit)
            return _apply_named_edit(session, session_id, user_id, pending_edit)
        picked_keywords, when_filter = _split_name_and_date_filter(message)
        if picked_keywords or when_filter is not None:
            candidates = pending_edit.candidates

            def candidate_words(candidate: EditCandidate) -> list[str]:
                return re.sub(r"[^a-z0-9 ]", " ", candidate.description.lower()).split()

            keywords_text = " ".join(picked_keywords)
            exact = [
                candidate
                for candidate in candidates
                if keywords_text
                and " ".join(candidate_words(candidate)) == keywords_text
                and (when_filter is None or candidate.when == when_filter)
            ]
            narrowed = exact or [
                candidate
                for candidate in candidates
                if (when_filter is None or candidate.when == when_filter)
                and all(
                    keyword in candidate_words(candidate) for keyword in picked_keywords
                )
            ]
            if not narrowed and when_filter is not None:
                narrowed = [
                    candidate
                    for candidate in candidates
                    if candidate.when == when_filter
                ]
            if len(narrowed) == 1:
                selected = narrowed[0]
                if pending_edit.op == "delete":
                    return _delete_preview_reply(session_id, user_id, selected)
                return _edit_preview_reply(
                    session_id, user_id, selected, pending_edit.new_amount
                )
            listing = "; ".join(
                f"{candidate.description} on {candidate.when.day} "
                f"{candidate.when.strftime('%b')} for SGD {candidate.amount:.2f}"
                for candidate in narrowed[:3]
            )
            pending_edit_store.put(
                user_id,
                PendingEdit(
                    new_amount=pending_edit.new_amount,
                    candidates=(narrowed or candidates)[:3],
                    candidate=None,
                    op=pending_edit.op,
                ),
            )
            if narrowed:
                return _local_reply(
                    session_id,
                    f"I found more than one match: {listing}. Which one did you mean? "
                    "Mention its date, for example 'the 21 Sep one'.",
                )
            return _local_reply(
                session_id,
                "None of those match — which one did you mean? "
                f"Your options: {listing or ', '.join(c.description for c in candidates)}.",
            )
        pending_edit_store.drop(user_id)

    delete_directive = DELETE_DIRECTIVE_PATTERN.match(message) or (
        DELETE_REQUEST_PATTERN.search(message)
        if EDIT_REQUEST_PATTERN.search(message) is None
        else None
    )
    if delete_directive is not None:
        named = TRANSACTION_NAME_PATTERN.search(message)
        target_text = delete_directive.group("target")
        if named is not None:
            target_text = f"{named.group('name')} {target_text}"
        keywords, when_filter = _split_name_and_date_filter(target_text)
        if not keywords:
            return _local_reply(
                session_id,
                "I couldn't find the transaction you meant. "
                "Mention its name, for example 'delete the Lunch transaction'.",
            )
        records = SQLAlchemyTransactionRepository(session).list_records(user_id)
        matches: list[EditCandidate] = []
        for record in records:
            words = set(re.sub(r"[^a-z0-9 ]", " ", record.description.lower()).split())
            if all(keyword in words for keyword in keywords):
                matches.append(
                    EditCandidate(
                        transaction_id=record.id,
                        description=record.description,
                        category=record.category,
                        amount=float(record.amount),
                        when=record.occurred_on,
                        recurring=record.recurring,
                    )
                )
        if when_filter is not None:
            matches = [candidate for candidate in matches if candidate.when == when_filter]
        if not matches:
            return _local_reply(
                session_id,
                f"I couldn't find a transaction matching "
                f"'{' '.join(keywords)}' in your records.",
            )
        matches.sort(key=lambda candidate: candidate.when, reverse=True)
        if len(matches) == 1:
            return _delete_preview_reply(session_id, user_id, matches[0])
        pending_edit_store.put(
            user_id,
            PendingEdit(
                new_amount=0.0, candidates=matches[:3], candidate=None, op="delete"
            ),
        )
        listing = "; ".join(
            f"{candidate.description} on {candidate.when.day} "
            f"{candidate.when.strftime('%b')} for SGD {candidate.amount:.2f}"
            for candidate in matches[:3]
        )
        return _local_reply(
            session_id,
            f"I found more than one match: {listing}. Which one did you mean? "
            "Mention its date, for example 'the 21 Sep one'.",
        )

    edit_directive = EDIT_DIRECTIVE_PATTERN.match(message) or EDIT_REQUEST_PATTERN.search(message)
    if edit_directive is not None:
        named = TRANSACTION_NAME_PATTERN.search(message)
        target_text = edit_directive.group("target")
        if named is not None:
            target_text = f"{named.group('name')} {target_text}"
        keywords, when_filter = _split_name_and_date_filter(target_text)
        try:
            new_amount = float(edit_directive.group("amount").replace(",", "."))
        except ValueError:
            new_amount = 0.0
        if new_amount <= 0:
            return None
        if not keywords:
            return _local_reply(
                session_id,
                "I couldn't find the transaction you meant. "
                "Mention its name, for example 'change the Lunch to 25'.",
            )
        records = SQLAlchemyTransactionRepository(session).list_records(user_id)
        matches: list[EditCandidate] = []
        for record in records:
            words = set(re.sub(r"[^a-z0-9 ]", " ", record.description.lower()).split())
            if all(keyword in words for keyword in keywords):
                matches.append(
                    EditCandidate(
                        transaction_id=record.id,
                        description=record.description,
                        category=record.category,
                        amount=float(record.amount),
                        when=record.occurred_on,
                        recurring=record.recurring,
                    )
                )
        if when_filter is not None:
            matches = [candidate for candidate in matches if candidate.when == when_filter]
        if not matches:
            return _local_reply(
                session_id,
                f"I couldn't find a transaction matching "
                f"'{' '.join(keywords)}' in your records.",
            )
        matches.sort(key=lambda candidate: candidate.when, reverse=True)
        if len(matches) == 1:
            return _edit_preview_reply(session_id, user_id, matches[0], new_amount)
        pending_edit_store.put(
            user_id,
            PendingEdit(new_amount=new_amount, candidates=matches[:3], candidate=None),
        )
        listing = "; ".join(
            f"{candidate.description} on {candidate.when.day} "
            f"{candidate.when.strftime('%b')} for SGD {candidate.amount:.2f}"
            for candidate in matches[:3]
        )
        return _local_reply(
            session_id,
            f"I found more than one match: {listing}. Which one did you mean? "
            "Mention its date, for example 'the 21 Sep one'.",
        )

    amendment = parse_last_saved_amendment(message)
    if amendment is not None:
        stored = last_saved_store.get(user_id)
        if stored is None:
            return None
        amount, when = amendment
        new_amount = stored.amount if amount is None else amount
        new_when = stored.when if when is None else when
        try:
            record = SQLAlchemyTransactionRepository(session).update(
                user_id,
                stored.transaction_id,
                TransactionCreate(
                    description=stored.description,
                    category=stored.category,
                    amount=ApplicationMoneyAmount(amount=new_amount),
                    occurred_on=new_when,
                    recurring=stored.recurring,
                ),
            )
            if record is None:
                last_saved_store.clear()
                return None
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            return _local_reply(
                session_id, "Sorry, I couldn't update that transaction. Please try again."
            )
        last_saved_store.remember(
            user_id,
            LastSavedRecord(
                transaction_id=stored.transaction_id,
                description=stored.description,
                category=stored.category,
                amount=new_amount,
                when=new_when,
                recurring=stored.recurring,
            ),
        )
        log_event("transaction.updated", source="coach_capture", category=stored.category)
        formatted = f"{new_when.day} {new_when.strftime('%b %Y')}"
        part = (
            f"{stored.description} is now SGD {new_amount:.2f} on {formatted} "
            f"under {stored.category.capitalize()}"
        )
        from app.services.budget_alert import category_overage_note

        note = category_overage_note(session, user_id, new_when.replace(day=1), stored.category)
        if note:
            part = part + " " + note.strip()
        return _local_reply(session_id, f"Updated: {part}.")

    return None


def _finalize(parts: list[str]) -> str:
    body = "; ".join(parts)
    return f"Saved: {body}" + ("" if body.endswith((".", "!")) else ".")


def _edit_preview_reply(
    session_id: str, user_id: str, candidate: EditCandidate, new_amount: float
) -> CoachResponse:
    pending_edit_store.put(
        user_id,
        PendingEdit(
            new_amount=new_amount,
            candidates=[candidate],
            candidate=candidate,
        ),
    )
    formatted = f"{candidate.when.day} {candidate.when.strftime('%b %Y')}"
    return _local_reply(
        session_id,
        f"Change {candidate.description} from SGD {candidate.amount:.2f} on {formatted} "
        f"to SGD {new_amount:.2f}? Reply 'confirm' to save, or 'cancel'.",
    )


def _delete_preview_reply(
    session_id: str, user_id: str, candidate: EditCandidate
) -> CoachResponse:
    pending_edit_store.put(
        user_id,
        PendingEdit(
            new_amount=0.0,
            candidates=[candidate],
            candidate=candidate,
            op="delete",
        ),
    )
    formatted = f"{candidate.when.day} {candidate.when.strftime('%b %Y')}"
    return _local_reply(
        session_id,
        f"Delete {candidate.description} for SGD {candidate.amount:.2f} on {formatted}? "
        "Reply 'confirm' to delete, or 'cancel'.",
    )


def _apply_named_delete(
    session: Session, session_id: str, user_id: str, pending_edit: PendingEdit
) -> CoachResponse:
    candidate = pending_edit.candidate
    assert candidate is not None
    try:
        removed = SQLAlchemyTransactionRepository(session).delete(
            user_id, candidate.transaction_id
        )
        if not removed:
            pending_edit_store.drop(user_id)
            return _local_reply(
                session_id, "I couldn't find that transaction anymore. Nothing was deleted."
            )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        return _local_reply(
            session_id, "Sorry, I couldn't delete that transaction. Please try again."
        )
    pending_edit_store.drop(user_id)
    log_event("transaction.deleted", source="coach_capture", category=candidate.category)
    formatted = f"{candidate.when.day} {candidate.when.strftime('%b %Y')}"
    return _local_reply(
        session_id,
        f"Deleted: {candidate.description} for SGD {candidate.amount:.2f} on {formatted}.",
    )


def _apply_named_edit(
    session: Session, session_id: str, user_id: str, pending_edit: PendingEdit
) -> CoachResponse:
    candidate = pending_edit.candidate
    assert candidate is not None
    new_amount = pending_edit.new_amount
    try:
        record = SQLAlchemyTransactionRepository(session).update(
            user_id,
            candidate.transaction_id,
            TransactionCreate(
                description=candidate.description,
                category=candidate.category,
                amount=ApplicationMoneyAmount(amount=new_amount),
                occurred_on=candidate.when,
                recurring=candidate.recurring,
            ),
        )
        if record is None:
            pending_edit_store.drop(user_id)
            return _local_reply(
                session_id, "I couldn't find that transaction anymore. Nothing was changed."
            )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        return _local_reply(
            session_id, "Sorry, I couldn't update that transaction. Please try again."
        )
    pending_edit_store.drop(user_id)
    log_event("transaction.updated", source="coach_capture", category=candidate.category)
    formatted = f"{candidate.when.day} {candidate.when.strftime('%b %Y')}"
    part = (
        f"{candidate.description} is now SGD {new_amount:.2f} on {formatted} "
        f"under {candidate.category.capitalize()}"
    )
    from app.services.budget_alert import category_overage_note

    note = category_overage_note(
        session, user_id, candidate.when.replace(day=1), candidate.category
    )
    if note:
        part = part + " " + note.strip()
    return _local_reply(session_id, f"Updated: {part}.")


def _start_capture(
    session_id: str,
    user_id: str,
    message: str,
    draft: CaptureDraft,
    save_one,
) -> CoachResponse:
    if draft.need_amount:
        pending_capture_store.put(user_id, draft)
        return _ask_amount_reply(session_id, draft)
    if draft.when is None:
        draft.when = extract_date_from_text(message, allow_future=draft.booking)
    if draft.when is not None:
        saved_part = save_one(draft, draft.when)
        answer = saved_part if saved_part.startswith("Sorry") else _finalize([saved_part])
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
