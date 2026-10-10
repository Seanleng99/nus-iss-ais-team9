"""Resolve bounded, read-only references without rewriting the user's request.

This stage selects a conversational subject, never a record ID, draft operation,
confirmation or calculation input. Unsupported or ambiguous references clarify.
"""

import re

from coach_i18n import input_pattern, load_data, request_locale, translate

from app.agents.education_access import (
    education_model_question,
    education_topics,
)
from app.core.schemas import AgentName, CoachRequest, FollowUpResolution

ORDINAL = re.compile(
    input_pattern("ai.core.follow_up.ordinal"),
    re.IGNORECASE,
)
ORDINAL_VALUES = load_data("input_vocabulary")["ordinal_values"]
NUMBERED = re.compile(input_pattern("ai.core.follow_up.numbered"), re.MULTILINE)
REFERENCE = re.compile(
    input_pattern("ai.core.follow_up.reference"),
    re.IGNORECASE,
)
ELLIPSIS = re.compile(
    input_pattern("ai.core.follow_up.ellipsis"),
    re.IGNORECASE,
)
READ = re.compile(
    input_pattern("ai.core.follow_up.read"),
    re.IGNORECASE,
)
ACTION = re.compile(
    input_pattern("ai.core.follow_up.action"),
    re.IGNORECASE,
)
SWITCH = re.compile(
    input_pattern("ai.core.follow_up.switch"), re.IGNORECASE
)
GOAL_REFERENCE = re.compile(
    input_pattern("ai.core.follow_up.goal_reference"), re.IGNORECASE
)


def resolve_follow_up(request: CoachRequest) -> FollowUpResolution:
    resolution = _resolve_follow_up(request)
    if resolution.status == "ambiguous":
        resolution.question = translate("conversation.choose_subject", request_locale(request))
    return resolution


def _resolve_follow_up(request: CoachRequest) -> FollowUpResolution:
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
        input_pattern("ai.core.follow_up.strong_reference"),
        message,
        re.IGNORECASE,
    )
    if not ordinal and _subject(message, request) and not strong_reference:
        return FollowUpResolution()
    if not ordinal and strong_reference:
        # A complete current sentence can establish the subject of a later
        # possessive in the same message. It must name exactly one education
        # concept; comparisons against an unresolved earlier subject still
        # use the normal history/ambiguity rules below.
        prefix = message[:strong_reference.start()]
        punctuation = input_pattern("ai.core.follow_up.sentence_punctuation")
        boundary = re.search("[" + re.escape(punctuation) + "]", prefix)
        current = _subject(prefix[:boundary.end()], request) if boundary else None
        references = list(re.finditer(input_pattern("ai.core.follow_up.strong_reference"), message, re.IGNORECASE))
        if (current and current.agent == AgentName.INVESTMENT_EDUCATION
                and len(current.education_topics) == 1
                and not re.search(input_pattern("ai.core.follow_up.multiple_subject_clause"),
                                  prefix[:boundary.end()], re.IGNORECASE)
                and all(re.fullmatch(input_pattern("ai.core.follow_up.possessive_reference"),
                                     match.group(), re.IGNORECASE) for match in references)):
            return FollowUpResolution(reason_code="CURRENT_MESSAGE_EDUCATION_SUBJECT")
    if ordinal:
        return _ordinal(request, ordinal)
    if GOAL_REFERENCE.search(message):
        return _goal(request)
    hint = (
        AgentName.BUDGET
        if re.search(input_pattern("ai.core.follow_up.hint"), message, re.IGNORECASE)
        else None
    )
    summary = request.session_context.older_summary
    prefer_older = bool(
        re.search(input_pattern("ai.core.follow_up.prefer_older"), message, re.IGNORECASE)
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
                input_pattern("ai.core.follow_up.possessive_reference"), message, re.IGNORECASE
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
        input_pattern("ai.core.follow_up.is_reference"),
        text,
        re.IGNORECASE,
    ):
        return False
    return bool(ELLIPSIS.fullmatch(text.strip()) or (REFERENCE.search(text) and READ.search(text)))


def _subject(text, request):
    # Unsupported scope does not erase explicitly named, supported subjects.
    # Answerability belongs to the specialist after reference resolution.
    topics = education_topics(text)
    if len(topics) > 12:
        return None
    if re.search(input_pattern("ai.core.follow_up.budget_subject"), text, re.IGNORECASE):
        agent = AgentName.BUDGET
    elif re.search(input_pattern("ai.core.follow_up.goal_subject"), text, re.IGNORECASE):
        agent = AgentName.GOAL_STRATEGY
    elif re.search(
        input_pattern("ai.core.follow_up.spending_subject"), text, re.IGNORECASE
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
    attributed = [item for item in request.session_context.referents if item.option_index is not None]
    if attributed:
        latest_position = max(item.source_position for item in attributed)
        options = [item for item in attributed if item.source_position == latest_position]
        indices = [item.option_index for item in options]
        # Rendered options are typed subjects with reviewed user provenance;
        # ordinary prose and subsequent formatting changes cannot lose them.
        if len(set(indices)) != len(indices) or sorted(indices) != list(range(1, len(indices) + 1)):
            if request.conversation_context:
                # Recover only from an available, unambiguous displayed option set.
                # The normal history boundary and unavailable-answer checks still apply.
                clean = request.session_context.model_copy(update={"referents": []})
                return _ordinal(request.model_copy(update={"session_context": clean}), match)
            return _ambiguous(message, "AMBIGUOUS_ATTRIBUTED_OPTIONS")
        number = 2 if value == "latter" and len(options) == 2 else ORDINAL_VALUES.get(value)
        selected = [item for item in options if item.option_index == number]
        if len(selected) != 1:
            return _ambiguous(message, "MISSING_ORDERED_OPTION")
        item = selected[0]
        return FollowUpResolution(
            status="resolved", agent=AgentName(item.agent), subject=item.subject,
            education_topics=item.education_topics, source_kind="attributed_referent",
            source_position=item.source_position, reason_code="ATTRIBUTED_ORDERED_OPTION",
        )
    def normalize(text):
        return " ".join(text.casefold().split()).rstrip(
            input_pattern("ai.core.follow_up.sentence_punctuation")
        )

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
        if not pairs:
            # Referents belong to the dialogue, not a particular Markdown
            # rendering. Preserve displayed order for bullet lists and tables.
            bullets = re.findall(r"^\s*[-*+]\s+(.+)$", item.content, re.MULTILINE)
            rows = []
            for line in item.content.splitlines():
                if not line.strip().startswith("|"):
                    continue
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                if cells and _subject(" ".join(cells), request):
                    rows.append(" ".join(cells))
            candidates = bullets or rows
            if len(candidates) >= 2 and all(_subject(text, request) for text in candidates):
                pairs = [(str(number), text) for number, text in enumerate(candidates, 1)]
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
        if re.search(
            input_pattern("ai.core.follow_up.goal"), item.content, re.IGNORECASE
        ) and not re.search(
            input_pattern("ai.core.follow_up.owned_goal_reference"), item.content, re.IGNORECASE
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
    return FollowUpResolution(
        status="ambiguous",
        reason_code=reason,
        question=translate('conversation.choose_subject', "en"),
    )
