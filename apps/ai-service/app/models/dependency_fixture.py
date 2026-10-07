"""Conservative English recognizers for offline tests, never production decisions."""

import re


def _parts(message):
    return [part.strip() for part in re.split(
        r"[.;!?]|\b(?:independently|separately)\b", message.casefold(),
    ) if part.strip()]


def fixture_goal_requires_capacity(payload):
    message = payload["message"]
    goal_parts = [part for part in _parts(message) if re.search(
        r"\b(?:goals?|targets?|contributions?|progress|remaining|deposit|vacation)\b", part,
    )]
    text = " ".join(goal_parts) or message.casefold()
    if payload.get("follow_up", {}).get("status") == "resolved":
        text += " " + payload["follow_up"].get("subject", "").casefold()
    if re.search(
        r"\b(?:afford\w*|feasib\w*|realistic|reach|achieve|sustainable|sufficient|enough|"
        r"on track|assess|evaluate|prioriti[sz]e|fund(?:ed|ing)?|can i|will i|should i)\b", text,
    ):
        return True
    return not bool(re.search(
        r"\b(?:calculate|arithmetic|remaining|progress|percentage|percent|contributions?|"
        r"monthly savings required|monthly saving required|explain|definition|general)\b", text,
    ))


def fixture_budget_uses_spending(payload):
    parts = _parts(payload["message"])
    budget_parts = [part for part in parts if re.search(r"\b(?:budget\w*|capacity|disposable)\b", part)]
    # A dynamically requested capacity provider owns the spending-informed Goal part.
    if payload.get("context_features", {}).get("goal_capacity_required"):
        budget_parts += [part for part in parts if re.search(r"\b(?:goal|goals)\b", part)]
    return any(
        re.search(r"\b(?:spending|transactions?|purchases|expenses?|history|useful context)\b", part)
        for part in budget_parts
    )


def fixture_budget_message(message):
    parts = [part for part in _parts(message) if re.search(r"\b(?:budget\w*|capacity|disposable)\b", part)]
    return " ".join(parts) or message
