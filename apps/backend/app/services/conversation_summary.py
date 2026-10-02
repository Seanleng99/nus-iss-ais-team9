"""Bounded extractive memory of older, completed and approved exchanges.

Keep exact excerpts instead of asking a model to invent persistent facts. The
checkpoint advances only with the parent chat state's successful transaction.
"""

import re
from copy import deepcopy

from coach_i18n import input_pattern

MAX_NOTES = 6
BACKFILL_MESSAGES = 128
TOPICS = {
    "spending": input_pattern("backend.services.conversation_summary.spending_topic"),
    "budget": input_pattern("backend.services.conversation_summary.budget_topic"),
    "goal_strategy": input_pattern("backend.services.conversation_summary.goal_topic"),
    "investment_education": input_pattern("backend.services.conversation_summary.investment_topic"),
}
PREFERENCE = re.compile(
    input_pattern("backend.services.conversation_summary.preference"),
    re.IGNORECASE,
)
OBJECTIVE = re.compile(
    input_pattern("backend.services.conversation_summary.objective"), re.IGNORECASE
)


def roll_summary(previous, messages, position, facts):
    from app.services.session_context import CORRECTION, UNSAFE, advance_state

    # The eight most recent messages stay verbatim; only whole older pairs roll
    # into memory. Positions are original chat-message positions, not turn IDs.
    cutoff = max(0, position - 9)
    summary = deepcopy(previous or {"through_position": 0, "notes": []})
    excluded = {fact["source_position"] for fact in facts.values()}
    excluded.update(
        fact["supersedes_position"] for fact in facts.values() if "supersedes_position" in fact
    )
    summary["notes"] = [
        note for note in summary["notes"] if note["source_position"] not in excluded
    ]
    if cutoff <= summary["through_position"]:
        return summary
    older = []
    for item in reversed(messages):
        if item.position > cutoff:
            continue
        if item.position <= summary["through_position"]:
            break
        older.append(item)
        if len(older) == BACKFILL_MESSAGES:
            break
    by_position = {item.position: item for item in reversed(older)}
    for item in by_position.values():
        if item.role != "user" or item.position in excluded:
            continue
        assistant = by_position.get(item.position + 1)
        # Missing provenance is fail-closed, just like recent assistant history.
        # In particular a blocked user's prompt must not become persistent memory.
        if not assistant or assistant.role != "assistant":
            continue
        trace = assistant.orchestration_trace
        if trace is None or trace.blocked:
            continue
        if (
            UNSAFE.search(item.content)
            or UNSAFE.search(assistant.content)
            or CORRECTION.match(item.content.strip())
        ):
            continue
        if advance_state(None, item.content, item.position)["facts"]:
            continue  # Structured, corrected facts are the only source for these values.
        user = " ".join(item.content.split())
        if not user:
            continue
        kind = (
            "preference"
            if PREFERENCE.search(user)
            else "objective"
            if OBJECTIVE.search(user)
            else "discussion"
        )
        summary["notes"].append(
            {
                "source_position": item.position,
                "assistant_position": assistant.position,
                "kind": kind,
                "topics": [
                    topic
                    for topic, pattern in TOPICS.items()
                    if re.search(pattern, user, re.IGNORECASE)
                ],
                "user_excerpt": _excerpt(user, 240),
                "assistant_excerpt": _excerpt(" ".join(assistant.content.split()), 160),
            }
        )
    # Repeated questions do not crowd out other context. Reserve up to two slots
    # for preferences/objectives, then retain the latest remaining discussions.
    unique = {note["user_excerpt"].casefold(): note for note in summary["notes"]}
    notes = sorted(unique.values(), key=lambda note: note["source_position"], reverse=True)
    salient = [note for note in notes if note["kind"] != "discussion"][:2]
    selected = salient + [note for note in notes if note not in salient][: MAX_NOTES - len(salient)]
    summary["notes"] = sorted(selected, key=lambda note: note["source_position"])
    summary["through_position"] = cutoff
    return summary


def _excerpt(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"
