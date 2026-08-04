from app.agents.base import BaseAgent
from app.core.schemas import AgentName, CoachRequest
from app.tools.registry import call_tool


class SpendingAgent(BaseAgent):
    name = AgentName.SPENDING
    prompt_id = "agent_spending"

    def _ground(self, request: CoachRequest, sanitized_message: str) -> dict:
        del sanitized_message
        totals = call_tool(self.name, "transaction_summarizer", request.snapshot)
        return {"category_totals": totals, "transaction_count": len(request.snapshot.recent_transactions)}
