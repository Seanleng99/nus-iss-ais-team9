from dataclasses import asdict

from app.agents.base import BaseAgent
from app.core.guardrails import sanitize_rag_document, validate_tool_permission
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentName, AgentTask
from app.models.gateway import ModelGateway
from app.rag.retriever import EducationRetriever


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
        contexts = []
        for item in self.education_retriever.retrieve(sanitized_message):
            context = asdict(item)
            decision = sanitize_rag_document(context["text"])
            context["text"] = decision.sanitized_text
            context["findings"] = list(dict.fromkeys([*context["findings"], *decision.findings]))
            contexts.append(context)
        sources = [
            {
                key: context[key]
                for key in (
                    "source_id",
                    "title",
                    "issuing_organization",
                    "canonical_url",
                    "published_at",
                    "document_version",
                    "checksum",
                    "corpus_version",
                    "review_due_at",
                )
            }
            for context in contexts
        ]
        return {
            "scope": "General investment education from approved sources without product advice.",
            "evidence_status": "grounded" if contexts else "insufficient",
            "corpus_version": getattr(
                self.education_retriever,
                "expected_corpus_version",
                getattr(self.education_retriever, "corpus_version", None),
            ),
            "contexts": contexts,
            "sources": sources,
        }
