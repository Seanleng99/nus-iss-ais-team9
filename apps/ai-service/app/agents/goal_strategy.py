from app.agents.base import BaseAgent
from app.core.schemas import AgentName, CoachRequest
from app.tools.registry import call_tool


class GoalStrategyAgent(BaseAgent):
    name = AgentName.GOAL_STRATEGY
    prompt_id = "agent_goal_strategy"

    def _ground(self, request: CoachRequest, sanitized_message: str) -> dict:
        del sanitized_message
        projections = call_tool(self.name, "goal_projection", request.snapshot)
        return {"projections": projections}
