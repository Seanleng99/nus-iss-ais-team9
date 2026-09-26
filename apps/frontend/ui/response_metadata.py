"""Describe response packaging without copying user or model content into logs."""

import re

_RESPONSE_FIELDS = (
    "session_id",
    "selected_agents",
    "answer",
    "agent_results",
    "disclaimers",
    "sources",
    "audit",
    "blocked",
    "role",
    "content",
    "explanation",
    "messages",
)
_AGENTS = {"spending", "budget", "goal_strategy", "investment_education", "risk_compliance"}


def response_metadata(response: object) -> dict:
    if not isinstance(response, dict):
        return {}
    explanation = response.get("explanation") or response.get("audit") or {}
    if not isinstance(explanation, dict):
        explanation = {}
    metadata = {"response_fields": [key for key in _RESPONSE_FIELDS if key in response]}
    trace_id = explanation.get("trace_id")
    if isinstance(trace_id, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", trace_id):
        metadata["trace_id"] = trace_id
    agents = response.get("selected_agents", explanation.get("selected_agents"))
    if isinstance(agents, list):
        metadata["selected_agents"] = [
            agent for agent in agents if isinstance(agent, str) and agent in _AGENTS
        ]
    blocked = response.get("blocked", explanation.get("blocked"))
    if isinstance(blocked, bool):
        metadata["blocked"] = blocked
    sources = response.get("sources")
    if isinstance(sources, list):
        metadata["source_count"] = len(sources)
    output = response.get("answer", response.get("content"))
    if isinstance(output, str):
        metadata["output_characters"] = len(output)
    return metadata
