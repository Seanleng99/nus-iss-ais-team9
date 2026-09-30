"""Explicit field syntax for offline goal-workflow tests and demos."""

import re

from app.agents.goal_capture import goal_change_request


def fixture_goal_draft(payload):
    message = payload["message"]
    pending = payload.get("pending_draft") or {}
    fields = dict(
        re.findall(
            r"(goal_id|goal_name|name|currency|target_amount|current_amount|target_months)\s*:\s*([^;\n]+)",
            message,
        )
    )
    if not goal_change_request(message) and not (pending and fields):
        return {"is_goal_request": False}
    draft = dict(pending)
    draft["questions"] = []
    for word, action in (
        ("create", "create"),
        ("add", "create"),
        ("update", "update"),
        ("edit", "update"),
        ("delete", "delete"),
        ("remove", "delete"),
    ):
        if re.search(r"\b" + word + r"\b", message, re.IGNORECASE):
            draft["action"] = action
            break
    for key, value in fields.items():
        value = value.strip()
        if key in {"target_amount", "current_amount", "target_months"}:
            try:
                value = int(value) if key == "target_months" else float(value)
            except ValueError:
                draft["questions"].append("Please provide a valid " + key)
                continue
        draft[key] = value
    return draft
