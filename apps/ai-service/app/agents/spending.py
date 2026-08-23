from app.agents.base import BaseAgent
from app.core.schemas import AgentName, AgentTask, UserFinancialSnapshot
from app.tools.registry import call_tool


class SpendingAgent(BaseAgent):
    name = AgentName.SPENDING
    prompt_id = "agent_spending"

    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del sanitized_message
        snapshot = UserFinancialSnapshot.model_validate(task.input_data)
        totals = call_tool(self.name, "transaction_summarizer", snapshot)
        return {
            "category_totals": totals,
            "transaction_count": len(snapshot.recent_transactions),
        }
