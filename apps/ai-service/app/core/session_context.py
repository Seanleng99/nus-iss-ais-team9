"""Minimize backend-provided conversational facts for each specialist."""

from app.agents.education_access import education_model_question
from app.core.guardrails import inspect_prompt
from app.core.schemas import AgentName, SessionContext

COACHING_PREFERENCE_KEYS = {
    "financial_literacy", "accessibility_preferences", "income_frequency", "income_stability",
    "household_size", "dependants", "housing_status", "preferred_style", "response_length",
}


def coaching_preferences(preferences: dict) -> dict:
    """One bounded allowlist shared by routing, specialists and synthesis."""
    result = {}
    for key, value in preferences.items():
        if key not in COACHING_PREFERENCE_KEYS:
            continue
        if isinstance(value, (str, int, bool)):
            valid = len(str(value)) <= 120
        else:
            valid = isinstance(value, list) and len(value) <= 8 and all(
                isinstance(item, str) and len(item) <= 64 for item in value
            )
        if valid and inspect_prompt(str(value)).allowed:
            result[key] = value
    return result


def attributed_turn_context(decision, request, message):
    """Drop model memory lacking an exact current user source before publishing it."""
    position = request.message_position or 1
    observations = []
    for item in decision.session_observations:
        if (item.source_position == position and item.source_quote in message
                and inspect_prompt(item.source_quote).allowed):
            observations.append(item)
    referents = []
    for item in decision.referents:
        if (item.source_position == position and item.source_quote in message
                and inspect_prompt(item.source_quote).allowed
                and inspect_prompt(item.subject).allowed):
            referents.append(item)
    decision.session_observations = observations
    decision.referents = referents
    return decision

ROLE_FIELDS = {
    AgentName.SPENDING: {"monthly_expenses", "budget_period_start"},
    AgentName.BUDGET: {"monthly_income", "monthly_expenses", "budget_period_start"},
    AgentName.GOAL_STRATEGY: {
        "monthly_income",
        "monthly_expenses",
        "goal_name",
        "goal_target_amount",
        "goal_current_amount",
        "goal_target_months",
    },
    AgentName.INVESTMENT_EDUCATION: {"goal_name", "goal_target_months"},
}


def specialist_context(context: SessionContext, agent: AgentName) -> dict:
    allowed = ROLE_FIELDS[agent]
    data = context.model_dump(exclude_none=True)
    data["facts"] = {key: value for key, value in data["facts"].items() if key in allowed}
    for field in ("pending_fields", "last_stated_fields", "uncertain_fields"):
        data[field] = [key for key in data[field] if key in allowed]
    data["observations"] = [
        item for item in data["observations"]
        if (not item["topics"] or agent.value in item["topics"])
        and (item.get("field") is None or item["field"] in allowed)
    ]
    data["referents"] = [item for item in data["referents"] if item["agent"] == agent.value]
    if data.get("older_summary"):
        notes = [
            note
            for note in data["older_summary"]["notes"]
            if not note["topics"] or agent.value in note["topics"]
        ]
        if agent == AgentName.INVESTMENT_EDUCATION:
            notes = [
                {
                    **note,
                    "user_excerpt": education_model_question(note["user_excerpt"]),
                    "assistant_excerpt": education_model_question(note["assistant_excerpt"]),
                }
                for note in notes
            ]
        data["older_summary"]["notes"] = notes
    if agent == AgentName.INVESTMENT_EDUCATION:
        data["observations"] = [
            {**item, "source_quote": education_model_question(item["source_quote"])}
            for item in data["observations"]
        ]
        data["referents"] = [
            {**item, "source_quote": education_model_question(item["source_quote"]),
             "subject": education_model_question(item["subject"])}
            for item in data["referents"]
        ]
    return data


def sanitized_summary(summary):
    if summary is None:
        return None
    notes = []
    for note in summary.notes:
        user = inspect_prompt(note.user_excerpt)
        assistant = inspect_prompt(note.assistant_excerpt)
        if user.allowed and assistant.allowed:
            notes.append(
                note.model_copy(
                    update={
                        "user_excerpt": user.sanitized_text[:240],
                        "assistant_excerpt": assistant.sanitized_text[:160],
                    }
                )
            )
    return summary.model_copy(update={"notes": notes})


def reported_value(task, field):
    context = task.context_features.get("session_context", {})
    if field in context.get("uncertain_fields", []):
        return None
    fact = context.get("facts", {}).get(field)
    return fact["value"] if fact and fact.get("status") == "user_reported" else None
