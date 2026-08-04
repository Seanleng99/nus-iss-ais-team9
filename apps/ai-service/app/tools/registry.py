from app.core.guardrails import validate_tool_permission
from app.core.schemas import AgentName, UserFinancialSnapshot
from app.rag.retriever import retrieve_trusted_context


def summarize_transactions(snapshot: UserFinancialSnapshot) -> dict[str, float]:
    totals: dict[str, float] = {}
    for transaction in snapshot.recent_transactions:
        totals[transaction.category] = totals.get(transaction.category, 0.0) + transaction.amount.amount
    return totals


def calculate_budget(snapshot: UserFinancialSnapshot) -> dict[str, float | str]:
    income = snapshot.monthly_income.amount if snapshot.monthly_income else 0.0
    recurring = sum(item.amount.amount for item in snapshot.recurring_expenses)
    disposable = max(income - recurring, 0.0)
    return {
        "income": round(income, 2),
        "recurring_expenses": round(recurring, 2),
        "disposable_income": round(disposable, 2),
        "needs": round(disposable * 0.5, 2),
        "wants": round(disposable * 0.3, 2),
        "savings": round(disposable * 0.2, 2),
        "method": "50/30/20 baseline after recurring expenses",
    }


def project_goals(snapshot: UserFinancialSnapshot) -> list[dict[str, float | str]]:
    projections: list[dict[str, float | str]] = []
    for goal in snapshot.goals:
        remaining = max(goal.target_amount.amount - goal.current_amount.amount, 0.0)
        monthly_required = remaining / goal.target_months
        projections.append(
            {
                "name": goal.name,
                "remaining": round(remaining, 2),
                "target_months": goal.target_months,
                "monthly_required": round(monthly_required, 2),
            }
        )
    return projections


def call_tool(agent: AgentName, tool_name: str, snapshot: UserFinancialSnapshot):
    validate_tool_permission(agent, tool_name)
    if tool_name == "transaction_summarizer":
        return summarize_transactions(snapshot)
    if tool_name == "budget_calculator":
        return calculate_budget(snapshot)
    if tool_name == "goal_projection":
        return project_goals(snapshot)
    raise KeyError(f"Unknown tool: {tool_name}")


def call_retrieval_tool(agent: AgentName, tool_name: str, query: str) -> list[dict[str, str]]:
    validate_tool_permission(agent, tool_name)
    if tool_name == "trusted_retriever":
        return retrieve_trusted_context(query)
    raise KeyError(f"Unknown retrieval tool: {tool_name}")
