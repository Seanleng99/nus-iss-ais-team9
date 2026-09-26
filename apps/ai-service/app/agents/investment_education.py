import re

from app.agents.base import BaseAgent
from app.agents.education_access import (
    apply_education_scope,
    build_minimal_education_query,
    education_gap_message,
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
    HybridEducationNarrative,
    SourceCitation,
)
from app.core.telemetry import log_event, trace_method
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
        if prompts.version in {"v6", "v7"}:
            self.narrative_type = HybridEducationNarrative

    @trace_method
    def _ground(self, task: AgentTask, sanitized_message: str) -> dict:
        validate_tool_permission(self.name, "education_retriever")
        response_language = education_response_language(sanitized_message)
        unsupported_topics = unsupported_education_topics(sanitized_message)
        try:
            query, query_topics = build_minimal_education_query(
                sanitized_message,
                additional_topics=task.context_features.get("education_topics", []),
            )
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
            # A provenance question needs actual source records, not a search
            # for documents containing the words "source verification".
            "General investment education about investment basics"
            if query_topics == ["source verification"] else query,
            scope="General investment education from approved sources without product advice.",
        )
        apply_education_scope(grounding, sanitized_message, query_topics)
        if "source verification" in query_topics:
            grounding["source_verification"] = True
        grounding["retrieval_consumer"] = self.name.value
        if self.narrative_type is HybridEducationNarrative and not grounding.get("security_findings"):
            # Model memory may explain stable concepts, never current rules or eligibility.
            grounding["fallback_topics"] = [
                topic for topic in query_topics
                if "CPF" not in topic
                and topic not in {"source verification", "investment limits"}
            ]
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
        if self.prompts.version == "v7" and narrative.summary and not SOURCE_MARKER.search(narrative.summary):
            raise ModelGatewayError(
                "The investment-education summary has no citation marker.",
                code="MISSING_CITATION",
                component=self.name.value,
            )
        grounding["cited_source_ids"] = cited_source_ids
        grounding["uncertainties"] = narrative.uncertainties
        if isinstance(narrative, HybridEducationNarrative):
            topics = [section.topic for section in narrative.general_knowledge]
            if topics and any(
                paragraph.strip() and not SOURCE_MARKER.search(paragraph)
                for paragraph in re.split(r"\n(?=\s*(?:[-*]|\d+[.)])\s)|\n\s*\n", narrative.summary)
            ):
                raise ModelGatewayError(
                    "Each sourced paragraph in a hybrid answer needs a supporting citation.",
                    code="MISSING_CITATION", component=self.name.value,
                )
            if (
                len(topics) != len(set(topics))
                or not set(topics).issubset(grounding.get("fallback_topics", []))
                or bool(narrative.summary.strip()) != bool(cited_source_ids)
            ):
                raise ModelGatewayError(
                    "Education content did not preserve its permitted scope and provenance.",
                    code="INVALID_EDUCATION_PROVENANCE", component=self.name.value,
                )
            for section in narrative.general_knowledge:
                validate_citations(section.text, [])
                if re.search(
                    r"\b(?:the|supplied|retrieved|provided|approved)\s+"
                    r"(?:(?:retrieved|education|approved|supplied)\s+)?"
                    r"(?:evidence|sources?|passages?|documents?)\b|"
                    r"(?:检索资料|知识库|资料)(?:显示|说明|描述|指出)",
                    section.text, re.IGNORECASE,
                ):
                    raise ModelGatewayError(
                        "Model-only education must not attribute claims to retrieved evidence.",
                        code="UNAPPROVED_CITATION", component=self.name.value,
                    )
            if not narrative.summary.strip() and not topics:
                grounding["evidence_status"] = "insufficient"
            if topics:
                grounding["general_knowledge"] = [
                    section.model_dump() for section in narrative.general_knowledge
                ]
                grounding["evidence_status"] = "hybrid" if narrative.summary.strip() else "general_knowledge"
                grounding["unanswered_topics"] = [
                    topic for topic in grounding.get("unanswered_topics", []) if topic not in topics
                ]
        return narrative

    @trace_method
    def _format_summary(self, narrative: AgentNarrative, grounding: dict) -> str:
        if not isinstance(narrative, HybridEducationNarrative) or not narrative.general_knowledge:
            return narrative.summary or education_gap_message(grounding)
        chinese = grounding.get("response_language") == "Chinese"
        parts = []
        if narrative.summary.strip():
            parts.append(("知识库资料：\n" if chinese else "From approved sources:\n") + narrative.summary)
        parts.append(
            ("一般知识补充（来自模型知识，未经本次检索资料验证）：\n" if chinese else
             "General educational background (model knowledge; not verified against retrieved sources):\n")
            + "\n".join("- " + section.text for section in narrative.general_knowledge)
        )
        log_event("education.answer.provenance", component="hybrid" if narrative.summary else "general_knowledge")
        return "\n\n".join(parts)

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
                    "funds (mutual funds, distinct from ETFs)" if topic == "funds" else topic
                    for topic in grounding["query_topics"]
                    if topic not in grounding.get("unanswered_topics", [])
                    or topic in grounding.get("fallback_topics", [])
                ) + ". Search the supplied evidence first; use the separate general_knowledge "
                "field only for missing stable concepts permitted by fallback_topics. "
                "Do not expand to adjacent topics."
            )
        return (
            "General investment education about "
            + ", ".join(
                topic for topic in grounding["query_topics"]
                if topic not in grounding.get("unanswered_topics", [])
            )
        )
