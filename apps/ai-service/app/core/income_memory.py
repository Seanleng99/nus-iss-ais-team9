"""Bounded income acknowledgements and recall from owned, user-reported chat facts."""

import re
from decimal import Decimal

from coach_i18n import input_pattern, translate
from coach_i18n import response_language as request_language

from app.core.schemas import AgentName, AgentResult, CoachRequest

NUMBER = r"(?:\d{1,12}|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?"
MONEY = rf"(?:SGD\s*|S?\$\s*)?(?P<amount>{NUMBER})(?:\s*SGD)?"
BARE_AMOUNT = re.compile(
    input_pattern("ai.core.income_memory.bare_amount", MONEY=MONEY), re.IGNORECASE
)
STATEMENT = re.compile(
    input_pattern("ai.core.income_memory.statement", MONEY=MONEY),
    re.IGNORECASE,
)
CORRECTION = re.compile(
    input_pattern("ai.core.income_memory.correction", MONEY=MONEY),
    re.IGNORECASE,
)
REMINDER = re.compile(
    input_pattern("ai.core.income_memory.reminder"),
    re.IGNORECASE,
)
CONTEXT_QUALIFIER = re.compile(
    r"this is (?:a (?:(?:browser|automated|manual) )?(?:regression )?test|a hypothetical (?:example|scenario))"
    r"(?: using (?:synthetic|hypothetical) (?:values|data))?[.!]*",
    re.IGNORECASE,
)
CHAT = r"(?:\s+(?:in|within)\s+(?:this|our)\s+(?:chat|conversation))?"
RECALL = re.compile(
    r"(?:what (?:monthly )?income (?:did|have) I (?:most recently )?(?:tell|told|give|given|report|reported) you(?: earlier)?"
    + CHAT
    + r"|what (?:did I tell|have I told) you about my (?:monthly )?income"
    + CHAT
    + r"|(?:have|did) I (?:given|provided|reported|stated) (?:you )?(?:a |my )?(?:monthly )?income(?: value)?"
    + CHAT
    + r"(?: yet)?|(?:do|can) you remember my (?:monthly )?income"
    + CHAT
    + input_pattern("ai.core.income_memory.recall"),
    re.IGNORECASE,
)


def income_memory_reply(request: CoachRequest) -> AgentResult | None:
    """Whole-message matching excludes mixed advice, calculations and record writes."""
    if request.requested_agents and set(request.requested_agents) != {AgentName.BUDGET}:
        return None
    context = request.session_context
    operation = "recall" if RECALL.fullmatch(request.message.strip()) else None
    if operation is None:
        if context.last_stated_fields != ["monthly_income"]:
            return None
        amounts = []
        for clause in re.split(
            input_pattern("ai.core.income_memory.clause_separator"), request.message.strip()
        ):
            clause = clause.strip()
            match = (
                STATEMENT.fullmatch(clause)
                or CORRECTION.fullmatch(clause)
                or BARE_AMOUNT.fullmatch(clause)
            )
            if match:
                amounts.append(Decimal(match["amount"].replace(",", "")))
            elif not (REMINDER.fullmatch(clause) or CONTEXT_QUALIFIER.fullmatch(clause)):
                return None
        fact = context.facts.get("monthly_income")
        if not amounts or not fact or any(amount != Decimal(fact.value) for amount in amounts):
            return None
        operation = "acknowledge"
    fact = context.facts.get("monthly_income")
    uncertain = "monthly_income" in context.uncertain_fields
    status = "uncertain" if uncertain else "known" if fact else "missing"
    if status == "known":
        amount = (
            format(Decimal(fact.value), ",f").rstrip("0").rstrip(".")
            if "." in fact.value
            else format(Decimal(fact.value), ",f")
        )
        if operation == "acknowledge":
            summary = (
                translate('income.acknowledge', request_language(request), amount=amount)
            )
        else:
            summary = (
                translate('income.recall', request_language(request), amount=amount)
            )
    elif status == "uncertain":
        summary = (
            translate('income.uncertain', request_language(request))
        )
    else:
        summary = (
            translate('income.missing', request_language(request))
        )
    return AgentResult(
        agent=AgentName.BUDGET,
        summary=summary,
        confidence=1.0,
        rationale=[
            translate('income.rationale', request_language(request))
        ],
        data={
            "income_memory": {
                "operation": operation,
                "status": status,
                "value": fact.value if fact and not uncertain else None,
                "source_position": fact.source_position if fact and not uncertain else None,
            },
            "needs_input": status != "known",
            **(
                {
                    "questions": [
                        translate('income.question', request_language(request))
                    ]
                }
                if status != "known"
                else {}
            ),
        },
    )


def verified_income_memory_reply(
    request: CoachRequest,
    results: list[AgentResult],
    draft_answer: str,
    routing_rationale: list[str] | None,
) -> bool:
    """Recompute the entire controlled reply; a marker alone is never authority."""
    expected = income_memory_reply(request)
    return bool(
        expected is not None
        and len(results) == 1
        and results[0] == expected
        and draft_answer == expected.summary
        and routing_rationale == expected.rationale
    )
