"""Small, attributable chat facts; never a financial-record write or model memory.

Only explicit supported statements and unambiguous clarification answers are
captured. Models cannot invent state, confirm it, or promote it into grounding.
"""

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal

from app.domain.schemas import CoachResponse

MONEY_FIELDS = {"monthly_income", "monthly_expenses", "goal_target_amount", "goal_current_amount"}
FIELDS = MONEY_FIELDS | {"goal_name", "goal_target_months", "budget_period_start"}
NUMBER = r"(?:\d{1,9}|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?"
MONEY = rf"(?:SGD\s*|S?\$\s*)?(?P<value>{NUMBER})(?:\s*SGD)?"
SUFFIX = r"(?:\s*(?:per month|a month|monthly|/month|每月))?"
PREFIX = r"(?:(?:actually|correction|sorry)[, :]*\s*)?"
LABELS = {
    "monthly_income": r"(?:(?:my\s+)?(?:monthly |take.home )?(?:income|salary)|I earn|我的(?:每月|月)?(?:收入|工资|薪水))",
    "monthly_expenses": r"(?:(?:my\s+)?(?:monthly |necessary monthly )?(?:expenses|spending)|我的(?:每月|月)?(?:支出|开销))",
    "goal_target_amount": r"(?:(?:my\s+)?(?:goal )?target(?: amount)?|目标金额)",
    "goal_current_amount": r"(?:(?:my\s+)?(?:current savings|currently saved|saved amount)|I have saved|已存金额)",
}
SEPARATOR = r"\s*(?:is|are|:|=|为|是)?\s*"
PATTERNS = {
    key: re.compile(rf"^{PREFIX}{label}{SEPARATOR}{MONEY}{SUFFIX}[.!。]*$", re.IGNORECASE)
    for key, label in LABELS.items()
}
PATTERNS["goal_target_months"] = re.compile(
    rf"^{PREFIX}(?:(?:my\s+)?(?:goal )?(?:duration|time horizon|target duration)|期限)"
    rf"{SEPARATOR}(?P<value>\d{{1,3}})\s*(?:months?|个月)[.!。]*$",
    re.IGNORECASE,
)
PATTERNS["goal_name"] = re.compile(
    rf"^{PREFIX}(?:(?:my\s+)?goal(?: name)?|目标名称){SEPARATOR}"
    r"(?P<value>[\w\u4e00-\u9fff][\w\u4e00-\u9fff -]{0,119})[.!。]*$",
    re.IGNORECASE,
)
FOREIGN_CURRENCY = re.compile(
    r"(?<![a-z])(?:USD|EUR|GBP|MYR|RM|AUD|HKD|JPY|CNY|RMB|US\$)(?![a-z])|[€£]", re.IGNORECASE
)
UNSAFE = re.compile(
    r"ignore.{0,25}instructions|reveal.{0,25}prompt|bypass.{0,25}(?:policy|safety)|"
    r"<\s*/?(?:system|developer)|忽略.{0,20}指令|泄露.{0,20}提示|[STFGM]\d{7}[A-Z]",
    re.IGNORECASE,
)
BARE_MONEY = re.compile(rf"^{MONEY}[.!。]*$", re.IGNORECASE)
MONTHS = {
    name: index
    for index, name in enumerate(
        (
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
        ),
        1,
    )
}
PERIOD = re.compile(r"(?P<month>" + "|".join(MONTHS) + r")\s+(?P<year>20\d{2})", re.IGNORECASE)
CORRECTION = re.compile(
    r"^(?:actually|correction|sorry|更正|其实)[, :，]*\s*(?:(?:it(?:['’]s| is)|that(?:['’]s| is))\s*)?",
    re.IGNORECASE,
)


def empty_state():
    return {
        "version": 1,
        "facts": {},
        "active_topic": None,
        "pending_fields": [],
        "last_stated_fields": [],
        "uncertain_fields": [],
        "pending_action": None,
    }


def _amount(value):
    amount = Decimal(value.replace(",", ""))
    return format(amount, "f") if 0 <= amount <= Decimal("999999999999.99") else None


def advance_state(previous, message, position):
    state = deepcopy(previous or empty_state())
    if UNSAFE.search(message):
        state["last_stated_fields"] = []
        return state
    updates = {}
    ambiguous = set()
    for clause in re.split(r"[;\n]|(?<=[.!?。])\s+", message.strip()):
        clause = clause.strip()
        if FOREIGN_CURRENCY.search(clause):
            continue
        for field, pattern in PATTERNS.items():
            match = pattern.fullmatch(clause)
            if not match:
                continue
            value = match["value"].strip()
            if field in MONEY_FIELDS:
                value = _amount(value)
            if field == "goal_target_months" and not 1 <= int(value) <= 600:
                value = None
            if value is not None:
                different = field in updates and (
                    Decimal(updates[field]) != Decimal(value)
                    if field in MONEY_FIELDS
                    else updates[field] != value
                )
                if different:
                    ambiguous.add(field)
                updates[field] = value
        if re.fullmatch(
            r"(?:my )?budget (?:month|period|for)\s*[:=]?\s*" + PERIOD.pattern + r"[.!]*",
            clause,
            re.IGNORECASE,
        ):
            match = PERIOD.search(clause)
            updates["budget_period_start"] = date(
                int(match["year"]), MONTHS[match["month"].lower()], 1
            ).isoformat()
    # A bare answer fills exactly one pending field. A correction can refer to
    # exactly one field explicitly stated in the immediately preceding turn.
    if not updates and not FOREIGN_CURRENCY.search(message):
        correction = CORRECTION.match(message.strip())
        fields = (
            state["last_stated_fields"] if correction and state["last_stated_fields"]
            else state["pending_fields"]
        )
        text = message.strip()[correction.end() :] if correction else message.strip()
        if len(fields) == 1 and fields[0] in MONEY_FIELDS:
            match = BARE_MONEY.fullmatch(text)
            if match:
                value = _amount(match["value"])
                if value is not None:
                    updates[fields[0]] = value
        elif len(fields) == 1 and fields[0] == "goal_target_months":
            match = re.fullmatch(r"(\d{1,3})\s*(?:months?|个月)?[.!。]*", text, re.IGNORECASE)
            if match and 1 <= int(match[1]) <= 600:
                updates[fields[0]] = match[1]
        elif fields == ["budget_period_start"]:
            match = PERIOD.fullmatch(text.rstrip(".!"))
            if match:
                updates[fields[0]] = date(
                    int(match["year"]), MONTHS[match["month"].lower()], 1
                ).isoformat()
    for field, value in updates.items():
        if field in ambiguous:
            continue
        old = state["facts"].get(field)
        fact = {"value": value, "source_position": position, "status": "user_reported"}
        if old and old["value"] != value:
            fact["supersedes_position"] = old["source_position"]
        state["facts"][field] = fact
    state["last_stated_fields"] = sorted(set(updates) - ambiguous)
    state["pending_fields"] = sorted((set(state["pending_fields"]) - set(updates)) | ambiguous)
    state["uncertain_fields"] = sorted((set(state["uncertain_fields"]) - set(updates)) | ambiguous)
    return state


def build_session_context(chat, message, position):
    state = chat.conversation_state if chat else None
    if state is None and chat:
        # Backfill supported facts in old chats, without treating assistant prose
        # as evidence. New chats retain compact state beyond the history window.
        by_position = {item.position: item for item in chat.messages[-64:]}
        for item in by_position.values():
            if item.role == "user":
                next_item = by_position.get(item.position + 1)
                if (
                    next_item
                    and next_item.orchestration_trace
                    and next_item.orchestration_trace.blocked
                ):
                    continue
                state = advance_state(state, item.content, item.position)
    return advance_state(state, message, position)


def complete_state(state, response):
    state = deepcopy(state)
    if response.blocked:
        return None
    source = response.audit.get("source")
    if source in {"spending_date_query", "transaction_capture"}:
        state["active_topic"] = "spending"
    elif source == "budget_alert":
        state["active_topic"] = "budget"
    elif response.selected_agents:
        topic = next((agent.value for agent in response.selected_agents if agent.value != "risk_compliance"), None)
        if topic:
            state["active_topic"] = topic
    fields = set(state["uncertain_fields"])
    for result in response.agent_results:
        for question in result.data.get("questions", []):
            lower = question.lower()
            if re.search(
                r"(?:what (?:is |monthly )|provide |share ).*monthly income|每月收入是多少", lower
            ):
                fields.add("monthly_income")
            if re.search(r"what goal amount|provide .*goal amount|目标金额是多少", lower):
                fields.add("goal_target_amount")
            if re.search(r"target date|what duration|provide .*duration|期限是多久", lower):
                fields.add("goal_target_months")
            if "month and year" in lower or "which month" in lower:
                fields.add("budget_period_start")
    state["pending_fields"] = sorted(fields)
    state["pending_action"] = (
        "budget_status" if source == "budget_alert" and "budget_period_start" in fields else None
    )
    return state


def budget_query_period(request):
    if request.budget_period_start:
        return request.budget_period_start
    periods = {date(int(match["year"]), MONTHS[match["month"].lower()], 1)
               for match in PERIOD.finditer(request.message)}
    if len(periods) > 1:
        raise ValueError("Which single month and year should I check?")
    if periods:
        return periods.pop()
    state = request.session_context
    if re.search(r"\bthat (?:month|budget)\b", request.message, re.IGNORECASE) or state.get("pending_action") == "budget_status":
        fact = state["facts"].get("budget_period_start")
        if fact and "budget_period_start" not in state["uncertain_fields"]:
            return date.fromisoformat(fact["value"])
        raise ValueError("Which month and year does that budget refer to?")
    return None


def budget_status_follow_up(request):
    state = request.session_context
    return (
        state.get("pending_action") == "budget_status"
        and state["last_stated_fields"] == ["budget_period_start"]
    )


def session_fact_reply(request):
    """Recall requests use user facts, never an inferred balance or record write."""
    if not re.fullmatch(
        r"(?:what (?:did I (?:tell|say to) you|have I told you)(?: about (?:my )?(?:income|expenses|goal))?"
        r"|(?:what|do you remember) (?:is |was )?(?:my )?(?:monthly income|monthly expenses|goal name)"
        r"|你还记得我的(?:收入|支出|目标)吗)[?？.!\s]*",
        request.message,
        re.IGNORECASE,
    ):
        return None
    state = request.session_context
    facts = state["facts"]
    selected = [key for key in facts if key not in state["uncertain_fields"]]
    lower = request.message.lower()
    if "income" in lower or "收入" in lower:
        selected = [key for key in selected if key == "monthly_income"]
    elif "expenses" in lower or "支出" in lower:
        selected = [key for key in selected if key == "monthly_expenses"]
    elif "goal" in lower or "目标" in lower:
        selected = [key for key in selected if key.startswith("goal_")]
    if not selected:
        answer = "I don't have a clear user-stated value for that in this chat yet. Please state or clarify it."
    else:
        entries = [
            f"{key.replace('_', ' ')}: {'SGD ' if key in MONEY_FIELDS else ''}{facts[key]['value']}"
            for key in selected
        ]
        answer = (
            "You told me in this chat: "
            + "; ".join(entries)
            + ". These are user-reported details, not confirmed saved records."
        )
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=[],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit={"source": "session_context"},
    )
