import re
from typing import Any

from app.domain.schemas import CoachResponse

OTHER_USER_TOKEN_PATTERN = re.compile(
    r"\b[a-z][a-z0-9]*(?:_?[a-z])?\d{2,}[a-z0-9_-]*\b", re.IGNORECASE
)

DATA_INTENT_PATTERN = re.compile(
    r"\b(?:spend\w*|spent|expense\w*|transaction\w*|purchas\w*|budget\w*|record\w*)\b",
    re.IGNORECASE,
)


def find_other_user_reference(message: str, user_id: str) -> str | None:
    if not DATA_INTENT_PATTERN.search(message):
        return None
    own = {part for part in re.split(r"[-_]", user_id.strip().lower()) if part}
    for match in OTHER_USER_TOKEN_PATTERN.finditer(message):
        token = match.group(0).strip(".,!?;:'\"").lower()
        if not token or token in own:
            continue
        return token
    return None


def other_user_data_reply(session_id: str) -> CoachResponse:
    audit: dict[str, Any] = {"source": "privacy_guard"}
    return CoachResponse(
        session_id=session_id,
        selected_agents=[],
        answer=(
            "I can't share another person's spending records. I can only access your "
            "own data, so please ask about your own transactions instead."
        ),
        agent_results=[],
        disclaimers=[],
        audit=audit,
    )
