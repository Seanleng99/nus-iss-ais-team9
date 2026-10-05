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


def roll_summary(previous, messages, position, facts, observations=None):
    from app.services.session_context import CORRECTION, UNSAFE, advance_state

    # The eight most recent messages stay verbatim; only whole older pairs roll
    # into memory. Positions are original chat-message positions, not turn IDs.
    cutoff = max(0, position - 9)
    summary = deepcopy(previous or {"through_position": 0, "notes": []})
    excluded = set()
    excluded.update(
        fact["supersedes_position"] for fact in facts.values() if "supersedes_position" in fact
    )
    retained = []
    for note in summary["notes"]:
        if note["source_position"] in excluded:
            if advance_state(None, note["user_excerpt"], note["source_position"])["facts"]:
                continue
            note["assistant_excerpt"] = ""
        retained.append(note)
    summary["notes"] = retained
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
        if item.role != "user":
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
        ):
            continue
        semantic = [note for note in observations or []
                    if note["source_position"] == item.position
                    and note["source_quote"] in item.content
                    and note["kind"] in {"preference", "objective", "discussion"}]
        if semantic:
            for note in semantic:
                summary["notes"].append({
                    "source_position": item.position,
                    "assistant_position": assistant.position,
                    "kind": note["kind"],
                    "topics": note["topics"],
                    "user_excerpt": note["source_quote"],
                    "assistant_excerpt": "" if item.position in excluded else _excerpt(
                        " ".join(assistant.content.split()), 160, salient=True
                    ),
                })
            continue
        # A turn can contain a fact and a preference. Retain its non-fact clauses
        # while corrected structured values remain the only numerical memory.
        from app.services.session_context import statement_clauses
        correction_turn = CORRECTION.match(item.content.strip())
        user = " ".join(
            clause for clause in statement_clauses(item.content)
            if not advance_state(None, clause, item.position)["facts"]
            and not (CORRECTION.match(clause) and not (PREFERENCE.search(clause) or OBJECTIVE.search(clause)))
            and (not correction_turn or PREFERENCE.search(clause) or OBJECTIVE.search(clause))
        )
        user = " ".join(user.split())
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
                "user_excerpt": _excerpt(user, 240, salient=True),
                "assistant_excerpt": (
                    "" if item.position in excluded or advance_state(None, item.content, item.position)["facts"]
                    else _excerpt(" ".join(assistant.content.split()), 160, salient=True)
                ),
            }
        )
    # Preserve distinct preferences/objectives before repetitive discussions.
    # Use all slots when needed instead of dropping everything after two facts.
    unique = {note["user_excerpt"].casefold(): note for note in summary["notes"]}
    notes = sorted(unique.values(), key=lambda note: note["source_position"], reverse=True)
    salient = [note for note in notes if note["kind"] != "discussion"][:MAX_NOTES]
    selected = salient + [note for note in notes if note not in salient][: MAX_NOTES - len(salient)]
    summary["notes"] = sorted(selected, key=lambda note: note["source_position"])
    summary["through_position"] = cutoff
    return summary


def _excerpt(text, limit, *, salient=False):
    if len(text) <= limit:
        return text
    if salient:
        clauses = [part.strip() for part in re.split(r"(?<=[.!?])\s+|;\s*", text) if part.strip()]
        priorities = [part for part in clauses if PREFERENCE.search(part) or OBJECTIVE.search(part)]
        if priorities:
            return _excerpt(" ".join(priorities), limit)
    # Keep a bounded beginning and ending so the last qualification survives.
    head = (limit - 3) // 2
    tail = limit - 3 - head
    return text[:head].rstrip() + " … " + text[-tail:].lstrip()
