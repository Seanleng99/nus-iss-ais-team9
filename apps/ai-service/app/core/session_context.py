"""Minimize backend-provided conversational facts for each specialist."""

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
    return data


def reported_value(task, field):
    context = task.context_features.get("session_context", {})
    if field in context.get("uncertain_fields", []):
        return None
    fact = context.get("facts", {}).get(field)
    return fact["value"] if fact and fact.get("status") == "user_reported" else None
