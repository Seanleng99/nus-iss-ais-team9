from app.agents.base import BaseAgent
from app.core.guardrails import validate_tool_permission
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentName, AgentTask
from app.models.gateway import ModelGateway
from app.rag.retriever import EducationRetriever, build_education_context


class InvestmentEducationAgent(BaseAgent):
    name = AgentName.INVESTMENT_EDUCATION
    prompt_id = "agent_investment_education"

    def __init__(
        self,
        gateway: ModelGateway,
        prompts: PromptCatalog,
        temperature: float,
        max_tokens: int,
        education_retriever: EducationRetriever,
    ) -> None:
        super().__init__(gateway, prompts, temperature, max_tokens)
        self.education_retriever = education_retriever

    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del task
        validate_tool_permission(self.name, "education_retriever")
        grounding = build_education_context(
            self.education_retriever,
            sanitized_message,
            scope="General investment education from approved sources without product advice.",
        )
        grounding["retrieval_consumer"] = self.name.value
        return grounding
