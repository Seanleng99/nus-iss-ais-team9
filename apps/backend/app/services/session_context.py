"""Attributable chat context, never financial-record writes or confirmation.

Legacy exact grammar remains a compatibility fallback. Model observations must
carry exact owned user excerpts, validated values, and clear attribution.
"""

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal

from coach_i18n import input_pattern, request_locale, translate
from pydantic import ValidationError

from app.domain.schemas import CoachResponse
from app.services.conversation_summary import roll_summary

MONEY_FIELDS = {"monthly_income", "monthly_expenses", "goal_target_amount", "goal_current_amount"}
FIELDS = MONEY_FIELDS | {"goal_name", "goal_target_months", "budget_period_start"}
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d{1,9})(?:\.\d{1,2})?(?:[kK])?"
MONEY = rf"(?:SGD\s*|S?\$\s*)?(?P<value>{NUMBER})(?:\s*SGD)?"
SUFFIX = input_pattern("backend.services.session_context.suffix")
PREFIX = r"(?:(?:actually|correction|sorry)[, :]*\s*)?"
LABELS = {
    "monthly_income": input_pattern("backend.services.session_context.monthly_income_label"),
    "monthly_expenses": input_pattern("backend.services.session_context.monthly_expenses_label"),
    "goal_target_amount": input_pattern(
        "backend.services.session_context.goal_target_amount_label"
    ),
    "goal_current_amount": input_pattern(
        "backend.services.session_context.goal_current_amount_label"
    ),
}
SEPARATOR = input_pattern("backend.services.session_context.separator")
PATTERNS = {
    key: re.compile(
        input_pattern(
            "backend.services.session_context.embedded_money_statement",
            PREFIX=PREFIX,
            label=label,
            SEPARATOR=SEPARATOR,
            MONEY=MONEY,
            SUFFIX=SUFFIX,
        ),
        re.IGNORECASE,
    )
    for key, label in LABELS.items()
}
PATTERNS["goal_target_months"] = re.compile(
    input_pattern(
        "backend.services.session_context.goal_target_months", PREFIX=PREFIX, SEPARATOR=SEPARATOR
    ),
    re.IGNORECASE,
)
PATTERNS["goal_name"] = re.compile(
    input_pattern("backend.services.session_context.goal_name", PREFIX=PREFIX, SEPARATOR=SEPARATOR),
    re.IGNORECASE,
)
FOREIGN_CURRENCY = re.compile(
    r"(?<![a-z])(?:USD|EUR|GBP|MYR|RM|AUD|HKD|JPY|CNY|RMB|US\$)(?![a-z])|[€£]", re.IGNORECASE
)
UNSAFE = re.compile(
    input_pattern("backend.services.session_context.unsafe"),
    re.IGNORECASE,
)
BARE_MONEY = re.compile(
    input_pattern("backend.services.session_context.bare_money", MONEY=MONEY), re.IGNORECASE
)
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
    input_pattern("backend.services.session_context.correction"),
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
        "observations": [],
        "referents": [],
    }


def _amount(value):
    value = value.replace(",", "")
    amount = Decimal(value[:-1]) * 1000 if value[-1:].lower() == "k" else Decimal(value)
    return format(amount, "f") if 0 <= amount <= Decimal("999999999999.99") else None


def statement_clauses(message):
    """Keep currency commas and decimals intact when reading compound statements."""
    return [
        clause.strip()
        for clause in re.split(
            input_pattern("backend.services.session_context.compound_separator"), message[:12000]
        )
        if clause.strip()
    ]


def _reported_clause(clause):
    if re.match(r"\s*(?:[\"`]|(?:how|what|is|are|could|would|should|can)\b)", clause, re.IGNORECASE):
        return False
    if any(mark in clause for mark in ('"', '`', '\u201c', '\u201d')) or re.search(r"(?<!\w)'[^']+'", clause):
        return False
    return not re.search(
        input_pattern("backend.services.session_context.unreported_clause"),
        clause, re.IGNORECASE,
    )


def advance_state(previous, message, position):
    state = deepcopy(previous or empty_state())
    if UNSAFE.search(message) or re.match(
        r"\s*(?:if|suppose|assuming|imagine|hypothetically|for example)\b", message, re.IGNORECASE
    ):
        state["last_stated_fields"] = []
        return state
    updates = {}
    ambiguous = set()
    for clause in statement_clauses(message):
        if FOREIGN_CURRENCY.search(clause) or not _reported_clause(clause):
            continue
        correction = CORRECTION.match(clause)
        if correction and len(updates) == 1:
            field = next(iter(updates))
            if field in MONEY_FIELDS:
                amount = BARE_MONEY.fullmatch(clause[correction.end():])
                if amount and (value := _amount(amount["value"])) is not None:
                    updates[field] = value
                    ambiguous.discard(field)
                    continue
        for field, pattern in PATTERNS.items():
            matches = list(pattern.finditer(clause)) if field in MONEY_FIELDS else [pattern.fullmatch(clause)]
            for match in matches:
                if not match:
                    continue
                # Different cadences and one-off purchases are not monthly facts.
                if field in {"monthly_income", "monthly_expenses"} and re.search(
                r"\b(?:per|a|each|every)\s+(?:day|week|fortnight|year)\b|\b(?:weekly|annually|yearly|today|yesterday)\b",
                    clause, re.IGNORECASE,
                ):
                    continue
                if field == "monthly_expenses" and re.match(r"I\s+(?:usually\s+)?spend\b", match[0], re.IGNORECASE) and not re.search(
                    input_pattern("backend.services.session_context.monthly_cadence"), clause, re.IGNORECASE
                ):
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
        if re.search(r"\b(?:goal|save|saving|target)\b", clause, re.IGNORECASE):
            duration = re.search(r"\b(?:in|within|over)\s+(\d{1,3})\s+months?\b", clause, re.IGNORECASE)
            if duration and 1 <= int(duration[1]) <= 600:
                if "goal_target_months" in updates and updates["goal_target_months"] != duration[1]:
                    ambiguous.add("goal_target_months")
                updates["goal_target_months"] = duration[1]
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
            match = re.fullmatch(
                input_pattern("backend.services.session_context.bare_duration"), text, re.IGNORECASE
            )
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
                if not next_item or not next_item.orchestration_trace or next_item.orchestration_trace.blocked:
                    continue
                state = advance_state(state, item.content, item.position)
    state = advance_state(state, message, position)
    state["older_summary"] = roll_summary(
        state.get("older_summary"), chat.messages if chat else [], position, state["facts"],
        state.get("observations", []),
    )
    return state


def _owned_quote(item, message, position):
    quote = item.source_quote
    return (item.source_position == position and quote in message
            and message.count(quote) == 1 and not UNSAFE.search(quote))


def _attributable_quote(message, quote):
    """Check the excerpt's own clause and quotation scope, not unrelated clauses."""
    if not _reported_clause(quote):
        return False
    start = message.find(quote)
    if start < 0:
        return False
    preceding = message[:start]
    if preceding.count('"') % 2 or preceding.count('`') % 2:
        return False
    if preceding.count('\u201c') > preceding.count('\u201d'):
        return False
    for match in re.finditer(r"(?<!\w)'[^']+'", message):
        if match.start() < start < match.end():
            return False
    # A hypothetical or other speaker before the excerpt governs it until a
    # sentence/semicolon boundary; later unrelated examples do not erase it.
    boundaries = list(re.finditer(r"[;\n]|(?<=[.!?])\s+", preceding))
    prefix = preceding[boundaries[-1].end():] if boundaries else preceding
    return not re.search(
        input_pattern("backend.services.session_context.unreported_clause"), prefix, re.IGNORECASE
    )


def _observation_value(item, message):
    """Interpretation may choose a field; the backend verifies the actual amount."""
    field, value, quote = item.field, item.value, item.source_quote
    if item.kind != "fact" or field not in FIELDS or value is None or item.attribution != "self":
        return None
    # A quote extracted from inside a conditional or attributed example cannot
    # become a self fact. Numeric equality alone is not sufficient provenance.
    if (not _attributable_quote(message, quote)
            or re.search(r"-\s*(?:SGD|S?\$)?\s*\d", quote, re.IGNORECASE)
            or FOREIGN_CURRENCY.search(quote)):
        return None
    if field in MONEY_FIELDS:
        if field in {"monthly_income", "monthly_expenses"} and (
            item.cadence != "monthly" or not re.search(
                input_pattern("backend.services.session_context.monthly_cadence"), quote, re.IGNORECASE
            )
        ):
            return None
        if not re.fullmatch(r"\d{1,12}(?:\.\d{1,2})?", value):
            return None
        amount = Decimal(value)
        quoted_values = {_amount(match[0]) for match in re.finditer(
            rf"(?<![\d.+-]){NUMBER}(?!\d|\.\d)", quote
        )}
        return value if amount <= Decimal("999999999999.99") and any(
            candidate is not None and Decimal(candidate) == amount for candidate in quoted_values
        ) else None
    if field == "goal_target_months":
        return value if value.isdecimal() and 1 <= int(value) <= 600 and re.search(
            rf"(?<!\d){re.escape(value)}(?!\d)", quote
        ) else None
    if field == "goal_name":
        return value if value in quote else None
    if field == "budget_period_start":
        try:
            period = date.fromisoformat(value)
        except ValueError:
            return None
        matches = list(PERIOD.finditer(quote))
        return value if period.day == 1 and (value in quote or any(
            period.year == int(match["year"]) and period.month == MONTHS[match["month"].lower()]
            for match in matches
        )) else None
    return None


def apply_observations(state, turn, message, position, answer=""):
    from app.domain.conversation_context import AttributedObservation, ConversationReferent

    if message is None or position is None or UNSAFE.search(message):
        return state
    observations, referents, updates = [], [], {}
    for raw in turn.get("session_observations", [])[:12]:
        try:
            item = AttributedObservation.model_validate(raw)
        except (ValidationError, TypeError):
            continue
        if not _owned_quote(item, message, position):
            continue
        value = _observation_value(item, message)
        if item.kind == "fact" and value is None:
            continue
        observations.append(item.model_dump(exclude_none=True))
        if value is not None:
            updates.setdefault(item.field, []).append(value)
    for field, values in updates.items():
        if len(set(values)) != 1:
            state["uncertain_fields"] = sorted(set(state["uncertain_fields"]) | {field})
            continue
        old = state["facts"].get(field)
        fact = {"value": values[0], "source_position": position, "status": "user_reported"}
        if old and old["value"] != values[0]:
            fact["supersedes_position"] = old["source_position"]
        state["facts"][field] = fact
        state["last_stated_fields"] = sorted(set(state["last_stated_fields"]) | {field})
        state["uncertain_fields"] = [key for key in state["uncertain_fields"] if key != field]
        state["pending_fields"] = [key for key in state["pending_fields"] if key != field]
    for raw in turn.get("referents", [])[:12]:
        try:
            item = ConversationReferent.model_validate(raw)
        except (ValidationError, TypeError):
            continue
        if (_owned_quote(item, message, position) and not UNSAFE.search(item.subject)
                and not re.search(r"\d|[$@]", item.subject)
                and (item.subject.casefold() in answer.casefold()
                     or item.subject.casefold() in item.source_quote.casefold())):
            referents.append(item.model_dump(exclude_none=True))
    # Latest exact preference excerpts and subjects remain available beyond the
    # verbatim window. Corrected facts replace prior field observations.
    existing = [item for item in state.get("observations", [])
                if item.get("field") not in updates]
    combined = existing + observations
    unique = {(item["kind"], item["source_quote"].casefold()): item for item in combined}
    ranked = sorted(unique.values(), key=lambda item: (
        item["kind"] in {"preference", "objective"}, item["source_position"]
    ), reverse=True)[:12]
    state["observations"] = sorted(ranked, key=lambda item: item["source_position"])
    unique_referents = {
        (item["source_position"], item.get("option_index"), item["subject"]): item
        for item in state.get("referents", []) + referents
    }
    state["referents"] = list(unique_referents.values())[-12:]
    return state


def complete_state(state, response, message=None, position=None):
    state = deepcopy(state)
    if response.blocked:
        return None
    turn = response.audit.get("turn_decision")
    if response.audit.get("presentation_rewritten") is True:
        # Option ordering belongs to the approved displayed answer. A rewrite
        # invalidates prior ordinals before new reviewed subjects are merged.
        state["referents"] = [item for item in state.get("referents", [])
                              if item.get("option_index") is None]
    if isinstance(turn, dict):
        apply_observations(state, turn, message, position, response.answer)
    source = response.audit.get("source")
    if source in {"spending_date_query", "transaction_capture", "spending_capture"} or response.audit.get("spending_capture"):
        state["active_topic"] = "spending"
    elif source == "budget_alert":
        state["active_topic"] = "budget"
    elif response.selected_agents:
        topic = next((agent.value for agent in response.selected_agents if agent.value != "risk_compliance"), None)
        if topic:
            state["active_topic"] = topic
    fields = set(state["uncertain_fields"])
    if isinstance(turn, dict):
        # New responses identify fields directly; phrasing, formatting and
        # language of their clarification questions cannot change memory.
        fields.update(field for field in turn.get("missing_fields", []) if field in FIELDS)
    for result in response.agent_results:
        if isinstance(turn, dict):
            fields.update(field for field in result.data.get("missing_fields", []) if field in FIELDS)
            continue
        for question in result.data.get("questions", []):
            lower = question.lower()
            if re.search(
                input_pattern("backend.services.session_context.income_clarification"), lower
            ):
                fields.add("monthly_income")
            if re.search(
                input_pattern("backend.services.session_context.goal_amount_clarification"), lower
            ):
                fields.add("goal_target_amount")
            if re.search(
                input_pattern("backend.services.session_context.duration_clarification"), lower
            ):
                fields.add("goal_target_months")
            if "month and year" in lower or "which month" in lower:
                fields.add("budget_period_start")
    state["pending_fields"] = sorted(fields)
    state["pending_action"] = (
        "budget_status" if (source == "budget_alert" or (turn or {}).get("budget_status_query"))
        and "budget_period_start" in fields else None
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


def session_fact_reply(request, *, semantic=False, fields=None):
    """Recall requests use user facts, never an inferred balance or record write."""
    if not semantic and not re.fullmatch(
        input_pattern("backend.services.session_context.recall_question"),
        request.message,
        re.IGNORECASE,
    ):
        return None
    state = request.session_context
    facts = state["facts"]
    selected = [key for key in facts if key not in state["uncertain_fields"]]
    lower = request.message.lower()
    if semantic:
        selected = [key for key in selected if fields is None or key in fields]
    elif "income" in lower or input_pattern("backend.services.session_context.income_term") in lower:
        selected = [key for key in selected if key == "monthly_income"]
    elif (
        "expenses" in lower
        or input_pattern("backend.services.session_context.expenses_term") in lower
    ):
        selected = [key for key in selected if key == "monthly_expenses"]
    elif "goal" in lower or input_pattern("backend.services.session_context.goal_term") in lower:
        selected = [key for key in selected if key.startswith("goal_")]
    if not selected:
        answer = translate("session_fact.empty", request_locale(request))
    else:
        locale = request_locale(request)
        entries = [
            f"{translate('session_fact.label.' + key, locale)}: {'SGD ' if key in MONEY_FIELDS else ''}{facts[key]['value']}"
            for key in selected
        ]
        answer = translate("session_fact.recall", locale, entries="; ".join(entries))
    return CoachResponse(
        session_id=request.session_id,
        selected_agents=[],
        answer=answer,
        agent_results=[],
        disclaimers=[],
        audit={"source": "session_context"},
    )
