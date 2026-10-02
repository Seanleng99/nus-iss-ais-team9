"""Resolve bounded, read-only references without rewriting the user's request.

This stage selects a conversational subject, never a record ID, draft operation,
confirmation or calculation input. Unsupported or ambiguous references clarify.
"""

import re

from app.agents.education_access import (
    education_model_question,
    education_topics,
    unsupported_education_topics,
)
from app.core.schemas import AgentName, CoachRequest, FollowUpResolution

ORDINAL = re.compile(
    r"\b(first|second|third|fourth|1st|2nd|3rd|4th|former|latter)\s+(?:option|point|item|one)\b|"
    r"\b(the former|the latter)\b|第([一二三四1234])个(?:选项|方案|要点)?",
    re.IGNORECASE,
)
ORDINAL_VALUES = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "1st": 1,
    "2nd": 2,
    "3rd": 3,
    "4th": 4,
    "former": 1,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
}
NUMBERED = re.compile(r"^\s*(?:\*\*)?(\d{1,2})[.)、]\s*(.+)$", re.MULTILINE)
REFERENCE = re.compile(
    r"\b(?:explain|clarify|review|compare|about|by|is|does|do)\s+(?:that|this|it|its|them|those|these)\b|"
    r"\b(?:that|this|those|these|earlier|previous)\s+(?:goal|budget|option|concept|point|topic|explanation)\b|"
    r"\b(?:discussed|mentioned|explained)\s+(?:earlier|previously)\b|\bits\s+(?:risk|cost|meaning)\b|"
    r"(?:那个|这个|那些|这些)(?:目标|预算|选项|概念|方案)|那是什么意思|它(?:的|们)?|之前的(?:目标|预算|概念)",
    re.IGNORECASE,
)
ELLIPSIS = re.compile(
    r"^(?:(?:please|can you|could you)\s+)?(?:tell me more|elaborate|give (?:me )?an example|"
    r"show (?:me )?an example|explain (?:again|more|more simply)|why)[?.!\s]*$|"
    r"^(?:再解释一下|说简单一点|举个例子|为什么)[？。！\s]*$",
    re.IGNORECASE,
)
READ = re.compile(
    r"\b(?:explain|what|why|how|tell|elaborate|example|compare|review)\b|解释|什么|怎样|怎么样|为何|为什么|例子|比较|看看",
    re.IGNORECASE,
)
ACTION = re.compile(
    r"\b(?:save|set|add|update|change|delete|remove|rename|record|confirm|adopt|buy|sell|execute|do it)\b|保存|确认|删除|修改|买入|卖出",
    re.IGNORECASE,
)
SWITCH = re.compile(
    r"\b(?:instead|new topic|switch|unrelated|rather than)\b|换个话题|改为", re.IGNORECASE
)
GOAL_REFERENCE = re.compile(
    r"\b(?:that|this|the)(?: earlier)? goal\b|那个目标|这个目标|之前的目标", re.IGNORECASE
)


def resolve_follow_up(request: CoachRequest) -> FollowUpResolution:
    message = request.message.strip()
    ordinal = ORDINAL.search(message)
    if ACTION.search(message) or SWITCH.search(message):
        return FollowUpResolution()
    if (
        not ordinal
        and not ELLIPSIS.fullmatch(message)
        and not (READ.search(message) and REFERENCE.search(message))
    ):
        return FollowUpResolution()
    # Pronouns inside a self-contained question can refer to its own nouns.
    # For example "Explain bonds and compare them with shares" starts a topic.
    strong_reference = re.search(
        r"\b(?:that|those|its|earlier|previously|this (?:goal|budget|option|concept))\b|那个|这个|之前|以前|它的",
        message,
        re.IGNORECASE,
    )
    if not ordinal and _subject(message, request) and not strong_reference:
        return FollowUpResolution()
    if ordinal:
        return _ordinal(request, ordinal)
    if GOAL_REFERENCE.search(message):
        return _goal(request)
    hint = AgentName.BUDGET if re.search(r"\bbudget\b|预算", message, re.IGNORECASE) else None
    summary = request.session_context.older_summary
    prefer_older = bool(
        re.search(r"\b(?:earlier|previously)\b|之前|以前", message, re.IGNORECASE)
        and summary
        and any(note.kind == "discussion" for note in summary.notes)
    )
    # A concrete new question is a boundary. Do not silently carry a subject
    # through unrelated history simply because an older topic is recognizable.
    indices = [] if prefer_older else range(len(request.conversation_context) - 1, -1, -1)
    for index in indices:
        item = request.conversation_context[index]
        if item.role != "user":
            continue
        previous_ordinal = ORDINAL.search(item.content)
        if previous_ordinal:
            previous_request = request.model_copy(
                update={
                    "message": item.content,
                    "conversation_context": request.conversation_context[:index],
                }
            )
            return _ordinal(previous_request, previous_ordinal)
        if _is_reference(item.content, request):
            continue
        candidate = _subject(item.content, request)
        if candidate:
            if hint and candidate.agent != hint:
                continue
            if len(candidate.education_topics) > 1 and re.search(
                r"\bits\b|它的", message, re.IGNORECASE
            ):
                return _ambiguous(message, "MULTIPLE_SUBJECTS")
            return candidate.model_copy(
                update={"source_kind": "recent_dialogue", "source_index": index}
            )
        selected = [
            agent for agent in request.requested_agents or [] if agent != AgentName.RISK_COMPLIANCE
        ]
        if len(selected) == 1:
            return _generic(selected[0], "explicit_agent", message)
        if not hint:
            return _ambiguous(message, "UNRELATED_OR_UNKNOWN_SUBJECT")
    candidates = []
    if summary:
        for note in summary.notes:
            if note.kind != "discussion" or _is_reference(note.user_excerpt, request):
                continue
            candidate = _subject(note.user_excerpt, request)
            if candidate and (not hint or candidate.agent == hint):
                candidates.append(
                    candidate.model_copy(
                        update={
                            "source_kind": "older_summary",
                            "source_position": note.source_position,
                        }
                    )
                )
    keys = {(item.agent, tuple(item.education_topics), item.subject) for item in candidates}
    if len(keys) == 1:
        return candidates[-1]
    if len(keys) > 1:
        return _ambiguous(message, "MULTIPLE_OLDER_SUBJECTS")
    selected = [
        agent for agent in request.requested_agents or [] if agent != AgentName.RISK_COMPLIANCE
    ]
    if len(selected) == 1:
        return _generic(selected[0], "explicit_agent", message)
    active = request.session_context.active_topic
    if active and active != AgentName.INVESTMENT_EDUCATION and (not hint or active == hint):
        return _generic(AgentName(active), "active_topic", message)
    return _ambiguous(message, "MISSING_SUBJECT")


def _is_reference(text, request):
    if _subject(text, request) and not re.search(
        r"\b(?:that|those|its|earlier|previously|this (?:goal|budget|option|concept))\b|那个|这个|之前|以前|它的",
        text,
        re.IGNORECASE,
    ):
        return False
    return bool(ELLIPSIS.fullmatch(text.strip()) or (REFERENCE.search(text) and READ.search(text)))


def _subject(text, request):
    if unsupported_education_topics(text):
        return None
    topics = education_topics(text)
    if len(topics) > 12:
        return None
    if re.search(r"\bbudget\b|预算", text, re.IGNORECASE):
        agent = AgentName.BUDGET
    elif re.search(r"\bgoal\b|目标", text, re.IGNORECASE):
        agent = AgentName.GOAL_STRATEGY
    elif re.search(
        r"\b(?:spend\w*|transaction\w*|expense\w*|dining)\b|支出|消费", text, re.IGNORECASE
    ):
        agent = AgentName.SPENDING
    elif topics:
        agent = AgentName.INVESTMENT_EDUCATION
    elif _goal_names(text, request):
        agent = AgentName.GOAL_STRATEGY
    else:
        return None
    return FollowUpResolution(
        status="resolved",
        agent=agent,
        subject=text[:240],
        education_topics=topics if agent == AgentName.INVESTMENT_EDUCATION else [],
        reason_code="ATTRIBUTABLE_SUBJECT",
    )


def _ordinal(request, match):
    message = request.message
    value = next(value for value in match.groups() if value)
    value = value.casefold().removeprefix("the ")
    def normalize(text):
        return " ".join(text.casefold().split()).rstrip(".?!。？！")

    for index in range(len(request.conversation_context) - 1, -1, -1):
        item = request.conversation_context[index]
        if item.role != "assistant":
            continue
        if item.answer_status != "available":
            # An unavailable response is not a new subject. Carry the original
            # options only across retries of this exact read-only question;
            # an unrelated user turn must still stop the lookup.
            if index > 0:
                previous = request.conversation_context[index - 1]
                if (
                    previous.role == "user"
                    and normalize(previous.content) == normalize(message)
                    and not ACTION.search(previous.content)
                    and not SWITCH.search(previous.content)
                ):
                    continue
            return _ambiguous(message, "MISSING_ORDERED_OPTIONS")
        pairs = NUMBERED.findall(item.content)
        options = {int(number): text.strip().strip("*") for number, text in pairs}
        if (
            len(options) != len(pairs)
            or not options
            or sorted(options) != list(range(1, len(options) + 1))
        ):
            return _ambiguous(message, "MISSING_ORDERED_OPTIONS")
        number = (
            2
            if value.casefold() == "latter" and len(options) == 2
            else ORDINAL_VALUES.get(value.casefold())
        )
        if number not in options:
            return _ambiguous(message, "MISSING_ORDERED_OPTION")
        candidate = _subject(options[number], request)
        if candidate:
            return candidate.model_copy(
                update={"source_kind": "recent_dialogue", "source_index": index}
            )
        return _ambiguous(message, "UNKNOWN_OPTION_SUBJECT")
    return _ambiguous(message, "MISSING_ORDERED_OPTIONS")


def _goal(request):
    context = request.session_context
    fact = context.facts.get("goal_name")
    if "goal_name" in context.uncertain_fields:
        return _ambiguous(request.message, "UNCERTAIN_GOAL_NAME")
    for index in range(len(request.conversation_context) - 1, -1, -1):
        item = request.conversation_context[index]
        if item.role != "user":
            continue
        names = _goal_names(item.content, request)
        if len(names) == 1:
            return FollowUpResolution(
                status="resolved",
                agent=AgentName.GOAL_STRATEGY,
                subject=names[0][:240],
                source_kind="recent_dialogue",
                source_index=index,
                reason_code="NAMED_GOAL_REFERENCE",
            )
        if len(names) > 1:
            return _ambiguous(request.message, "MULTIPLE_GOALS")
        if fact and fact.value.casefold() in item.content.casefold():
            return _reported_goal(request, fact)
        if re.search(r"\bgoal\b|目标", item.content, re.IGNORECASE) and not re.search(
            r"\b(?:my|the|that|this) goal\b|我的目标|那个目标|这个目标", item.content, re.IGNORECASE
        ):
            return _ambiguous(request.message, "REFERENCED_GOAL_NOT_IN_SAVED_CONTEXT")
    if fact:
        return _reported_goal(request, fact)
    older = {}
    if context.older_summary:
        for note in context.older_summary.notes:
            if note.kind != "discussion":
                continue
            names = _goal_names(note.user_excerpt, request)
            if len(names) > 1:
                return _ambiguous(request.message, "MULTIPLE_OLDER_GOALS")
            if names:
                older[names[0]] = note.source_position
    if len(older) == 1:
        name, position = next(iter(older.items()))
        return FollowUpResolution(
            status="resolved",
            agent=AgentName.GOAL_STRATEGY,
            subject=name[:240],
            source_kind="older_summary",
            source_position=position,
            reason_code="OLDER_NAMED_GOAL_REFERENCE",
        )
    if len(older) > 1:
        return _ambiguous(request.message, "MULTIPLE_OLDER_GOALS")
    if len(request.snapshot.goals) == 1:
        return FollowUpResolution(
            status="resolved",
            agent=AgentName.GOAL_STRATEGY,
            subject=request.snapshot.goals[0].name[:240],
            source_kind="saved_goal",
            reason_code="SINGLE_SAVED_GOAL",
        )
    return _ambiguous(request.message, "MISSING_OR_MULTIPLE_GOALS")


def _reported_goal(request, fact):
    if sum(goal.name.casefold() == fact.value.casefold() for goal in request.snapshot.goals) > 1:
        return _ambiguous(request.message, "DUPLICATE_GOAL_NAMES")
    return FollowUpResolution(
        status="resolved",
        agent=AgentName.GOAL_STRATEGY,
        subject=fact.value,
        source_kind="session_fact",
        source_position=fact.source_position,
        reason_code="USER_REPORTED_GOAL_REFERENCE",
    )


def _generic(agent, source, message):
    if agent == AgentName.INVESTMENT_EDUCATION:
        return _ambiguous(message, "MISSING_EDUCATION_SUBJECT")
    return FollowUpResolution(
        status="resolved",
        agent=agent,
        subject=agent.value,
        source_kind=source,
        reason_code="KNOWN_SPECIALIST_CONTEXT",
    )


def _goal_names(text, request):
    names = []
    for goal in request.snapshot.goals:
        if not goal.name.strip():
            continue
        pattern = re.escape(goal.name)
        if re.match(r"[A-Za-z0-9]", goal.name):
            pattern = r"(?<!\w)" + pattern
        if re.search(r"[A-Za-z0-9]$", goal.name):
            pattern += r"(?!\w)"
        if re.search(pattern, text, re.IGNORECASE):
            names.append(goal.name)
    return names


def specialist_follow_up(resolution, agent):
    if resolution.status == "standalone" or (resolution.agent and resolution.agent != agent):
        return {}
    data = resolution.model_dump(exclude_none=True)
    if agent == AgentName.INVESTMENT_EDUCATION and data.get("subject"):
        data["subject"] = education_model_question(data["subject"])
    return data


def _ambiguous(message, reason):
    chinese = bool(re.search(r"[\u4e00-\u9fff]", message))
    return FollowUpResolution(
        status="ambiguous",
        reason_code=reason,
        question="你指的是哪个目标、选项或概念？"
        if chinese
        else "Which goal, option or concept do you mean?",
    )
