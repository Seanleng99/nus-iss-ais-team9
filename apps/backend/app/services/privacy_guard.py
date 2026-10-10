import re
from typing import Any

from coach_i18n import input_pattern, translate

from app.core.telemetry import log_event
from app.domain.schemas import CoachResponse

OTHER_USER_TOKEN_PATTERN = re.compile(
    r"\b[a-z][a-z0-9]*(?:_?[a-z])?\d{2,}[a-z0-9_-]*\b", re.IGNORECASE
)

# "sgd600" or "rm100" is an amount, not a username.
CURRENCY_AMOUNT_TOKEN = re.compile(
    r"^(?:sgd|usd|us|eur|gbp|aud|nzd|cad|hkd|jpy|cny|rmb|myr|rm|idr|thb|php|inr|s)"
    r"\d+(?:\.\d+)?k?$"
)

DATA_INTENT_PATTERN = re.compile(
    r"\b(?:spend\w*|spent|expense\w*|transaction\w*|purchas\w*|budget\w*|record\w*|"
    r"goals?|savings|income|salary|balances?)\b",
    re.IGNORECASE,
)

# Keep in step with CROSS_USER_DATA_ACCESS_REGEXES in the AI service's Risk & Compliance agent.
DATA_NOUN = (
    r"(?:transactions?|spending|spendings|expenses?|purchases?|budgets?|goals?|savings|"
    r"income|salary|salaries|wages?|pay|payslips?|balances?|accounts?|finances|"
    r"financial\s+(?:data|records?|details|info(?:rmation)?)|records?|"
    r"bank\s+(?:details|statements?)|net\s+worth|investments?|portfolio|debts?|loans?|"
    r"bills?|cash\s*flow)\b"
)
FINANCIAL_VERB = (
    r"(?:spend|spent|spending|earn|earns|earned|earning|make|makes|made|save|saves|saved|"
    r"saving|pay|pays|paid|buy|buys|bought|owe|owes|budget|budgets|budgeted)\b"
)
READ_INTENT = (
    r"\b(?:show|tell|give|list|see|view|check|compare|share|reveal|display|get|find|"
    r"look\s*up|pull\s*up|access|what|how\s+much|how\s+many)\b"
)
RELATION = (
    r"(?:my|our|a|the)\s+(?:(?:best|close|good|old)\s+)?"
    r"(?:friend|colleague|co-?worker|boss|manager|wife|husband|spouse|partner|girlfriend|"
    r"boyfriend|mother|mom|mum|father|dad|sister|brother|son|daughter|parent|neighbou?r|"
    r"room-?mate|flatmate|housemate|classmate|cousin|uncle|aunt|relative|client|customer)s?"
)
OTHERS = (
    r"(?:someone|somebody|anyone|anybody|everyone|everybody)\s+else|"
    r"(?:another|other|different)\s+(?:user|person|people|member|customer|client)s?"
)
POSSESSIVE = r"(?:'s|s')"
GAP = r"(?:[\w-]+\s+){0,2}"

THIRD_PARTY_PATTERNS = (
    # "my colleague's spending", "someone else's goals": clearly about another person.
    (
        "relation_data",
        re.compile(rf"\b(?:{RELATION}|{OTHERS}){POSSESSIVE}?\s+{DATA_NOUN}", re.IGNORECASE),
    ),
    # "what is my friend's monthly spending?", "show me her goals".
    (
        "requested_third_party_data",
        re.compile(
            rf"{READ_INTENT}[^.?!]{{0,40}}"
            rf"\b(?:{RELATION}{POSSESSIVE}?|(?:{OTHERS}){POSSESSIVE}?|her|his|their)\s+"
            rf"{GAP}{DATA_NOUN}",
            re.IGNORECASE,
        ),
    ),
    # "how much does my sister earn?", "what did she spend?".
    (
        "third_party_activity",
        re.compile(
            rf"\b(?:did|does|do|has|have|is|was|will)\s+"
            rf"(?:{RELATION}|{OTHERS}|she|he)\s+(?:\w+\s+)?{FINANCIAL_VERB}",
            re.IGNORECASE,
        ),
    ),
    (
        "chinese_third_party_data",
        re.compile(
            input_pattern("backend.services.privacy_guard.third_party_patterns")
        ),
    ),
)

# A capitalised name owning financial data, or doing something financial:
# "show me John's transactions", "how much did Sarah spend".
NAMED_DATA_PATTERN = re.compile(
    rf"{READ_INTENT}[^.?!]{{0,40}}\b(?<!\bat\s)(?<!\bon\s)(?<!\bmy\s)(?<!\bfrom\s)(?<!\bin\s)"
    rf"(?P<name>(?-i:[A-Z][a-z]+))'s\s+{GAP}{DATA_NOUN}",
    re.IGNORECASE,
)
NAMED_ACTIVITY_PATTERN = re.compile(
    rf"\b(?:did|does|has|is|was|will)\s+(?P<name>(?-i:[A-Z][a-z]+))\s+(?:\w+\s+)?{FINANCIAL_VERB}",
    re.IGNORECASE,
)
# Possessives that are dates or merchants, not people.
NON_PERSON_NAMES = frozenset(
    {
        "today", "tonight", "yesterday", "tomorrow", "this", "last", "next", "that", "it",
        "what", "who", "there", "here", "let", "week", "month", "year", "everyone",
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december", "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday", "mcdonald", "macdonald", "sainsbury",
        "domino", "wendy", "denny", "levi", "kellogg",
    }
)


def _normalize(message: str) -> str:
    log_event("VV entering ", "app.services.privacy_guard", "_normalize")
    return " ".join(message.replace("’", "'").replace("‘", "'").split())


def _own_name_tokens(user_id: str) -> set[str]:
    log_event("VV entering ", "app.services.privacy_guard", "_own_name_tokens")
    return {part for part in re.split(r"[-_]", user_id.strip().lower()) if part}


def _other_username(message: str, own: set[str]) -> str | None:
    log_event("VV entering ", "app.services.privacy_guard", "_other_username")
    if not DATA_INTENT_PATTERN.search(message):
        return None
    for match in OTHER_USER_TOKEN_PATTERN.finditer(message):
        token = match.group(0).strip(".,!?;:'\"").lower()
        if not token or token in own or CURRENCY_AMOUNT_TOKEN.match(token):
            continue
        before, after = message[max(0, match.start() - 40):match.start()], message[match.end():]
        # Compact date/amount/product tokens are not requests for an account.
        if re.fullmatch(r"on\d{1,2}", token) and re.match(r"/\d{1,2}\b", after):
            continue
        owned_item = re.search(r"\b(?:my|our)\s+$", before, re.IGNORECASE)
        identifier_context = re.search(r"\b(?:user|account|profile|member|customer)\s*[:=]?\s*$", before, re.IGNORECASE)
        if not identifier_context and re.fullmatch(r"(?:over|under|above|below|min|max)\d+(?:k)?", token):
            continue
        financial_subject = re.match(rf"(?:'s)?\s+{GAP}(?:{DATA_NOUN}|{FINANCIAL_VERB})", after, re.IGNORECASE)
        if identifier_context or (financial_subject and not owned_item):
            return token
    return None


HOUSEHOLD_FACT = re.compile(
    r"\b(?:my|our)\s+(?:wife|husband|spouse|partner)(?:'s)?\s+"
    r"(?:(?:monthly|net|gross|take.home|regular)\s+)?"
    r"(?:income|salary|earnings|expenses|spending|debts|savings)\s*"
    r"(?:is|are|was|were|equals|of|:)?\s*(?:SGD|S\$|\$)?\s*"
    r"\d+(?:[,.]\d+)*(?:k)?\b", re.IGNORECASE,
)


def _without_supplied_household_facts(message):
    log_event("VV entering ", "app.services.privacy_guard", "_without_supplied_household_facts")
    def supplied(match):
        log_event("VV entering ", "app.services.privacy_guard", "_without_supplied_household_facts.supplied")
        prefix = message[max(0, match.start() - 80):match.start()]
        prefix = re.split(r"[.?!;\n]", prefix)[-1]
        # An explicit lookup stays guarded even if an amount appears later.
        direct_lookup = re.search(r"\b(?:show|tell|give|get|find)\s+(?:me\s+)?(?:the\s+)?$", prefix, re.IGNORECASE)
        fetch = re.search(r"\b(?:fetch|access|retrieve|look\s*up|pull\s*up|download|reveal|query)\b", prefix, re.IGNORECASE)
        return match.group() if direct_lookup or fetch else " "
    return HOUSEHOLD_FACT.sub(supplied, message)


def _named_person(message: str, own: set[str]) -> str | None:
    log_event("VV entering ", "app.services.privacy_guard", "_named_person")
    for pattern in (NAMED_DATA_PATTERN, NAMED_ACTIVITY_PATTERN):
        for match in pattern.finditer(message):
            name = match.group("name").lower()
            if name not in own and name not in NON_PERSON_NAMES:
                return f"named_person:{name}"
    return None


def find_other_user_reference(message: str, user_id: str) -> str | None:
    """Return why a request asks for another person's financial data, or None.

    The backend only ever loads the signed-in user's own records; this stops the
    coach from answering as though it could see someone else's.
    """
    log_event("VV entering ", "app.services.privacy_guard", "find_other_user_reference")
    text = _without_supplied_household_facts(_normalize(message))
    own = _own_name_tokens(user_id)
    username = _other_username(text, own)
    if username is not None:
        return username
    for label, pattern in THIRD_PARTY_PATTERNS:
        if pattern.search(text):
            return label
    return _named_person(text, own)


def other_user_data_reply(session_id: str) -> CoachResponse:
    log_event("VV entering ", "app.services.privacy_guard", "other_user_data_reply")
    audit: dict[str, Any] = {"source": "privacy_guard"}
    return CoachResponse(
        session_id=session_id,
        selected_agents=[],
        answer=translate("privacy.other_user_data"),
        agent_results=[],
        disclaimers=[],
        audit=audit,
    )
