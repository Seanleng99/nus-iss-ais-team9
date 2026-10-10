"""Bounded metadata for completed coaching requests; never retain request text."""

import re

from coach_i18n import load_data

from app.core.telemetry import log_event

AGENTS = {"budget", "spending", "goal_strategy", "investment_education", "risk_compliance"}


def observation(request, response) -> dict:
    text = request.message
    chinese = bool(re.search(load_data("scripts")["han_inventory"], text))
    latin = any(char.isascii() and char.isalpha() for char in text)
    language = "mixed" if chinese and latin else "zh" if chinese else "en" if latin else "other"
    length = len(text)
    agents = sorted({getattr(agent, "value", agent) for agent in response.selected_agents} & AGENTS)
    audit = response.audit
    capture = next((agent for agent in ("budget", "spending", "goal")
                    if audit.get(agent + "_capture")), None)
    return {
        "input_language": language,
        "input_length_band": "short" if length <= 100 else "medium" if length <= 500 else "long",
        "agent_mix": ".".join(agents) or "none",
        "intent_bucket": "capture_" + capture if capture else "analysis",
        "needs_input": any(result.data.get("status") == "needs_input"
                           or result.data.get("needs_input") is True for result in response.agent_results),
        "blocked": response.blocked,
        "model_id": audit.get("model_id"),
        "prompt_content_hash": audit.get("prompt_content_hash"),
        "build_commit": audit.get("build_commit"),
    }


def log_observation(request, response) -> None:
    log_event("coach.drift.observation", **observation(request, response))
