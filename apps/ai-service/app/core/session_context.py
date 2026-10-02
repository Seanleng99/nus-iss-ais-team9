"""Minimize backend-provided conversational facts for each specialist."""

from app.agents.education_access import education_model_question
from app.core.guardrails import inspect_prompt
from app.core.schemas import AgentName, SessionContext

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
