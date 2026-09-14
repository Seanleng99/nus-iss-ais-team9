from app.agents.base import BaseAgent
from app.agents.education_access import (
    apply_education_scope,
    build_minimal_education_query,
    education_response_language,
    unsupported_education_topics,
)
from app.core.citations import SOURCE_MARKER, validate_citations
from app.core.guardrails import validate_tool_permission
from app.core.prompts import PromptCatalog
from app.core.schemas import (
    AgentName,
    AgentNarrative,
    AgentTask,
    GroundedEducationNarrative,
    SourceCitation,
)
from app.core.telemetry import trace_method
from app.models.gateway import ModelGateway, ModelGatewayError
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
        if prompts.version in {"v5", "v6", "v7"}:
            self.narrative_type = GroundedEducationNarrative

    @trace_method
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        del task
        validate_tool_permission(self.name, "education_retriever")
        response_language = education_response_language(sanitized_message)
        unsupported_topics = unsupported_education_topics(sanitized_message)
        try:
            query, query_topics = build_minimal_education_query(sanitized_message)
        except ValueError:
            return {
                "scope": (
                    "General investment education from approved sources without "
                    "product advice."
                ),
                "evidence_status": "insufficient",
                "corpus_version": getattr(
                    self.education_retriever,
                    "expected_corpus_version",
                    getattr(self.education_retriever, "corpus_version", None),
                ),
                "contexts": [],
                "sources": [],
                "query_topics": [],
                "unanswered_topics": unsupported_topics,
                "response_language": response_language,
                "retrieval_consumer": self.name.value,
            }
        grounding = build_education_context(
            self.education_retriever,
            query,
            scope="General investment education from approved sources without product advice.",
        )
        apply_education_scope(grounding, sanitized_message, query_topics)
        grounding["retrieval_consumer"] = self.name.value
        return grounding

    @trace_method
    def _validate_narrative(
        self,
        narrative: AgentNarrative,
        grounding: dict,
    ) -> AgentNarrative:
        if not isinstance(narrative, GroundedEducationNarrative):
            return narrative
        approved_source_ids = {
            str(source["source_id"])
            for source in grounding.get("sources", [])
        }
        cited_source_ids = list(dict.fromkeys(narrative.source_ids))
        if not set(cited_source_ids).issubset(approved_source_ids):
            raise ModelGatewayError(
                "The investment-education response cited an unapproved source.",
                code="UNAPPROVED_CITATION",
                component=self.name.value,
            )
        sources = [
            SourceCitation.model_validate(source) for source in grounding["sources"]
            if source["source_id"] in cited_source_ids
        ]
        for text in (narrative.summary, *narrative.rationale, *narrative.uncertainties):
            validate_citations(text, sources)
        if self.prompts.version == "v7" and not SOURCE_MARKER.search(narrative.summary):
            raise ModelGatewayError(
                "The investment-education summary has no citation marker.",
                code="MISSING_CITATION",
                component=self.name.value,
            )
        grounding["cited_source_ids"] = cited_source_ids
        grounding["uncertainties"] = narrative.uncertainties
        return narrative

    @trace_method
    def _model_message(
        self,
        task: AgentTask,
        sanitized_message: str,
        grounding: dict,
    ) -> str:
        del task, sanitized_message
        if self.prompts.version in {"v6", "v7"}:
            return (
                "Answer the requested " + grounding.get("question_intent", "explanation")
                + " about " + ", ".join(
                    topic for topic in grounding["query_topics"]
                    if topic not in grounding.get("unanswered_topics", [])
                ) + ". Use only the provided evidence; do not expand to adjacent topics."
            )
        return (
            "General investment education about "
            + ", ".join(
                topic for topic in grounding["query_topics"]
                if topic not in grounding.get("unanswered_topics", [])
            )
        )
