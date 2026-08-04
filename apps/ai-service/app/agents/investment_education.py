from app.agents.base import BaseAgent
from app.core.schemas import AgentName, CoachRequest


class InvestmentEducationAgent(BaseAgent):
    name = AgentName.INVESTMENT_EDUCATION
    prompt_id = "agent_investment_education"

    def _ground(self, request: CoachRequest, sanitized_message: str) -> dict:
        del request, sanitized_message
        return {
            "scope": "General investment education without retrieved sources or product advice."
        }
