from app.agents.base import BaseAgent
from app.core.schemas import AgentName, CoachRequest
from app.tools.registry import call_tool


class BudgetAgent(BaseAgent):
    name = AgentName.BUDGET
    prompt_id = "agent_budget"

    def _ground(self, request: CoachRequest, sanitized_message: str) -> dict:
        del sanitized_message
        return call_tool(self.name, "budget_calculator", request.snapshot)
