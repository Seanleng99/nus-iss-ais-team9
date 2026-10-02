"""Bounded income acknowledgements and recall from owned, user-reported chat facts."""

import re
from decimal import Decimal

from app.agents.education_access import education_response_language
from app.core.schemas import AgentName, AgentResult, CoachRequest

NUMBER = r"(?:\d{1,12}|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?"
MONEY = rf"(?:SGD\s*|S?\$\s*)?(?P<amount>{NUMBER})(?:\s*SGD)?"
BARE_AMOUNT = re.compile(rf"{MONEY}[.!。]*", re.IGNORECASE)
STATEMENT = re.compile(
    rf"(?:(?:actually|correction|sorry)[, :]*\s*)?"
    rf"(?:(?:my\s+)?(?:monthly |take.home )?(?:income|salary)|I earn|我的(?:每月|月)?(?:收入|工资|薪水))"
    rf"\s*(?:is|:|=|为|是)?\s*{MONEY}(?:\s*(?:per month|a month|monthly|/month|每月))?[.!。]*",
    re.IGNORECASE,
)
CORRECTION = re.compile(
    rf"(?:actually|correction|sorry|更正|其实)[, :，]*\s*"
    rf"(?:(?:it(?:['’]s| is)|that(?:['’]s| is))\s*)?{MONEY}[.!。]*",
    re.IGNORECASE,
)
REMINDER = re.compile(
    r"(?:please\s+)?remember (?:it|this|my (?:monthly )?income)(?: (?:within|in) this chat)?[.!]*|"
    r"请?(?:在这个对话中)?记住(?:它|我的收入)[。！]*",
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
    + r"|我(?:之前|最近)?(?:在这个对话中)?(?:告诉|报给)你的(?:月收入|收入)是多少|"
    r"我(?:在这个对话中)?(?:提供|说过)月收入(?:了吗|吗))[?？.!。]*",
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
        for clause in re.split(r"[;\n]|(?<=[.!?。])\s+", request.message.strip()):
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
    chinese = education_response_language(request.message) == "Chinese"
    status = "uncertain" if uncertain else "known" if fact else "missing"
    if status == "known":
        amount = (
            format(Decimal(fact.value), ",f").rstrip("0").rstrip(".")
            if "." in fact.value
            else format(Decimal(fact.value), ",f")
        )
        if operation == "acknowledge":
            summary = (
                f"我已记下你在这个对话中提供的月收入 SGD {amount}。这是你提供的数值，未经独立核实；没有更改已保存的财务记录。"
                if chinese
                else f"I've noted your user-reported monthly income of SGD {amount} for this chat. "
                "It is not independently verified, and no saved financial records have been changed."
            )
        else:
            summary = (
                f"你最近在这个对话中提供的月收入是 SGD {amount}。这是你提供的数值，不是已确认的财务记录。"
                if chinese
                else f"You most recently reported monthly income of SGD {amount} in this chat. "
                "That is user-reported, not a confirmed financial record."
            )
    elif status == "uncertain":
        summary = (
            "这个对话中的月收入数值还不明确。你希望在这个对话中使用哪个数值？"
            if chinese
            else "Your reported monthly income is unclear in this chat. What value should I use for this chat?"
        )
    else:
        summary = (
            "这个对话中没有明确记录你提供的月收入。你的每月收入是多少？"
            if chinese
            else "I don't have a clearly recorded user-reported monthly income in this chat. What is your monthly income?"
        )
    return AgentResult(
        agent=AgentName.BUDGET,
        summary=summary,
        confidence=1.0,
        rationale=[
            "仅使用用户提供的对话事实；没有更改已保存的记录。"
            if chinese
            else "Only owned user-reported chat facts are used; no saved records are changed."
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
                        "你的每月收入是多少？" if chinese else "What is your monthly income?"
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
