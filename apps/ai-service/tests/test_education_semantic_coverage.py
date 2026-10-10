"""Offline tests of production query interpretation and exact-evidence contracts."""

import json

import pytest

from app.agents.investment_education import InvestmentEducationAgent
from app.core.config import Settings
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentName, AgentTask, CoachRequest, HybridEducationNarrative
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.answerability import (
    EducationAnswerability,
    EducationQueryPlan,
    assess_answerability,
    build_query_plan,
    evidence_passages,
    validate_answerability,
)
from app.rag.retriever import RetrievedChunk

QUOTE = "An ETF may differ from the index it tracks because of fees and timing."
PLAN = {
    "subquestions": [{
        "question_id": "q1", "topic": "tracking error",
        "public_question": "Why can an ETF differ from its index?",
        "query_terms": ["tracking error", "fees"],
    }],
}


def coverage(*, status="supported", quote=QUOTE, source_id="etf-source"):
    return {"coverage": [{
        "question_id": "q1", "status": status,
        "supporting_passages": [] if status == "unsupported" else [{"source_id": source_id, "quote": quote}],
        "limitation": "" if status == "supported" else "The passage does not explain the requested mechanism.",
    }]}


class ScriptedSemanticGateway:
    """Script the semantic calls without pretending the fixture understands meaning."""

    def __init__(self, *, plan=PLAN, support=None):
        self.plan = plan
        self.support = coverage() if support is None else support
        self.calls = []

    def count_input_tokens(self, **kwargs):
        # No provider request occurs in this unmetered offline double.
        return 0

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        component = kwargs["system_prompt"].splitlines()[0]
        if component == "PROMPT_ID: education_query_planner":
            return json.dumps(self.plan)
        if component == "PROMPT_ID: education_answerability":
            return json.dumps(self.support)
        if component == "PROMPT_ID: agent_investment_education":
            return json.dumps({
                "summary": QUOTE + " [source:etf-source]",
                "source_ids": ["etf-source"], "rationale": ["Evidence explains the difference."],
                "confidence": 0.8, "uncertainties": [], "general_knowledge": [],
            })
        return LocalFixtureModelGateway().generate(**kwargs)


class RecordingRetriever:
    expected_corpus_version = "investment-education-sg@test-v1"

    def __init__(self, text=QUOTE):
        self.queries = []
        self.text = text

    def retrieve(self, query, top_k=3):
        self.queries.append(query)
        return [RetrievedChunk(
            source_id="etf-source", title="Saved ETF guide", issuing_organization="MoneySense",
            canonical_url="https://www.moneysense.gov.sg/investments/etfs",
            published_at="2026-07-02", document_version="2026-07-02",
            checksum="sha256:" + "a" * 64,
            corpus_version=self.expected_corpus_version, review_due_at="2099-12-31",
            text=self.text, score=0.9,
        )][:top_k]


def task(message="Explain ETFs."):
    return AgentTask(
        task_id="education-task",
        agent=AgentName.INVESTMENT_EDUCATION, sanitized_message=message,
        input_data={}, context_features={},
    )


def test_paraphrase_becomes_public_concepts_and_quote_backed_answer():
    retriever = RecordingRetriever()
    gateway = ScriptedSemanticGateway()
    response = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="openai"), gateway=gateway, education_retriever=retriever,
    ).handle(CoachRequest(
        user_id="synthetic", session_id="synthetic",
        message=("Why can a basket that follows a market measure drift from that measure? "
                 "My salary is SGD 9876 and email is learner@example.com."),
        requested_agents=["investment_education"],
    ))
    assert not response.blocked
    assert "because of fees and timing" in response.answer
    data = response.agent_results[0].data
    assert data["retrieval_strategy"] == "model_public_concept_plan"
    assert data["coverage_assessment"] == "model_semantic_with_exact_quotes"
    assert data["subquestion_coverage"][0]["supporting_passages"][0]["quote"] == QUOTE
    assert any("tracking error" in query for query in retriever.queries)
    assert all("9876" not in query and "learner" not in query and "salary" not in query
               for query in retriever.queries)
    planner = next(call for call in gateway.calls if "education_query_planner" in call["system_prompt"])
    assert "learner@example.com" not in planner["user_prompt"]
    assert "9876" not in planner["user_prompt"]


def test_keyword_presence_does_not_upgrade_unsupported_subquestion():
    retriever = RecordingRetriever("An ETF tracks an index. Fees are mentioned in this guide.")
    gateway = ScriptedSemanticGateway(support=coverage(status="unsupported"))
    agent = InvestmentEducationAgent(gateway, PromptCatalog(), 0.2, 1600, retriever)
    grounding = agent._ground(task(), "Explain why an ETF can differ from its index.")
    assert grounding["subquestion_coverage"][0]["status"] == "unsupported"
    assert not grounding["coverage_source_ids"]
    assert "tracking error" in grounding["unanswered_topics"]
    narrative = HybridEducationNarrative(
        summary="Fees explain the difference. [source:etf-source]", source_ids=["etf-source"],
        rationale=["A keyword matched."], confidence=0.8,
    )
    with pytest.raises(ModelGatewayError, match="supporting a requested subquestion"):
        agent._validate_narrative(narrative, grounding)


def test_resolved_convexity_keeps_distinct_fallback_scope_for_writer_and_review():
    from app.agents.risk_compliance import RiskComplianceAgent

    class ConvexityGateway(ScriptedSemanticGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: agent_investment_education\n"):
                self.calls.append(kwargs)
                return json.dumps({"summary": "", "source_ids": [], "rationale": ["Stable concept."],
                    "confidence": 0.8, "uncertainties": [], "general_knowledge": [{
                        "topic": "bond convexity", "text": "Convexity describes curvature in a bond's price-yield relation; duration describes its local slope.",
                    }]})
            return super().generate(**kwargs)

    gateway = ConvexityGateway(plan={"subquestions": [{"question_id": "q1", "topic": "bond convexity",
        "public_question": "How does bond convexity describe price-yield curvature?", "query_terms": ["convexity"]}]},
        support=coverage(status="unsupported"))
    prompts = PromptCatalog()
    agent = InvestmentEducationAgent(gateway, prompts, 0.2, 1600, RecordingRetriever())
    request_task = task("Tell me more, with a simple example.")
    request_task.context_features.update(education_topics=["bonds"], conversation_context=[
        {"role": "user", "content": "Explain bond convexity as a stable textbook concept."},
        {"role": "assistant", "content": "Convexity concerns price-yield curvature."},
    ])
    result = agent.run_task(request_task).result
    assert result.data["query_topics"] == ["bond convexity"]
    assert result.data["fallback_topics"] == ["bond convexity"]
    assert not result.data["coverage_source_ids"]
    assert result.data["general_knowledge"][0]["topic"] == "bond convexity"
    policy = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture", _env_file=None), gateway=LocalFixtureModelGateway(),
    ).policy_retriever
    RiskComplianceAgent(gateway, prompts, 0, 1600, policy).validate(
        CoachRequest(user_id="synthetic", session_id="synthetic", message=request_task.sanitized_message),
        [result], result.summary,
    )
    sent = json.loads(gateway.calls[-1]["user_prompt"])
    assert sent["agent_results"][0]["data"]["fallback_topics"] == ["bond convexity"]


def test_unverified_source_status_is_rendered_once_without_dropping_concept_scope():
    from app.agents.education_access import education_gap_message

    agent = InvestmentEducationAgent(ScriptedSemanticGateway(), PromptCatalog(), 0, 1600, RecordingRetriever())
    grounding = {"coverage_assessment": "semantic_contract_unverified", "sources": [], "contexts": [],
        "fallback_topics": ["bonds"], "unanswered_topics": ["bonds"], "excluded_topics": [],
        "response_language": "English"}
    narrative = HybridEducationNarrative(summary="", source_ids=[], rationale=["Stable concept."], confidence=0.8,
        general_knowledge=[{"topic": "bonds", "text": "A bond is a loan to an issuer; repayment depends on its terms and ability to pay."}],
        uncertainties=["Source support could not be verified."])
    with pytest.raises(ModelGatewayError, match=r"Set uncertainties=\[\]"):
        agent._validate_narrative(narrative, grounding)
    narrative.uncertainties = []
    agent._validate_narrative(narrative, grounding)
    answer = agent._format_summary(narrative, grounding)
    assert answer.count(education_gap_message(grounding)) == 1
    assert "ability to pay" in answer


@pytest.mark.parametrize("quote,source_id", [
    ("An ETF always matches its index.", "etf-source"),
    (QUOTE, "wrong-source"),
])
def test_answerability_rejects_invented_quotes_or_wrong_source(quote, source_id):
    with pytest.raises(ModelGatewayError, match="exact text"):
        validate_answerability(
            EducationAnswerability.model_validate(coverage(quote=quote, source_id=source_id)),
            EducationQueryPlan.model_validate(PLAN),
            [{"source_id": "etf-source", "text": QUOTE}],
        )


def test_incomplete_coverage_contract_is_rejected():
    with pytest.raises(ModelGatewayError, match="every subquestion"):
        validate_answerability(
            EducationAnswerability(coverage=[]), EducationQueryPlan.model_validate(PLAN), [],
        )


def test_passage_selection_resolves_exact_server_text_without_model_transcription():
    contexts = [{"source_id": "etf-source", "text": QUOTE + "\n\nLosses remain possible."}]
    decision = EducationAnswerability.model_validate(coverage(quote=""))
    support = decision.coverage[0].supporting_passages[0]
    support.source_id = None
    support.passage_id = "p1"
    result = validate_answerability(decision, EducationQueryPlan.model_validate(PLAN), contexts)
    assert result.coverage[0].supporting_passages[0].quote == QUOTE
    assert result.coverage[0].supporting_passages[0].source_id == "etf-source"


@pytest.mark.parametrize("passage_id,source_id,quote", [
    ("p999", None, ""), ("p1", "invented-source", ""), ("p1", None, "Changed wording"),
])
def test_passage_reference_cannot_change_evidence(passage_id, source_id, quote):
    decision = EducationAnswerability.model_validate(coverage(quote=quote))
    support = decision.coverage[0].supporting_passages[0]
    support.passage_id, support.source_id = passage_id, source_id
    with pytest.raises(ModelGatewayError, match="unchanged carried evidence"):
        validate_answerability(decision, EducationQueryPlan.model_validate(PLAN), [{"source_id": "etf-source", "text": QUOTE}])


def test_long_passage_catalog_keeps_contiguous_exact_spans_and_qualifications():
    text = ("Public explanation of diversification. " * 50) + "Diversification does not eliminate losses."
    contexts = [{"source_id": "education-source", "text": text}]
    catalog = evidence_passages(contexts)
    assert len(catalog) > 1
    assert "".join(item["quote"] for item in catalog) == text
    assert all(len(item["quote"]) <= 1200 for item in catalog)
    assert "does not eliminate losses" in catalog[-1]["quote"]


def test_answerability_input_carries_text_once_and_preserves_context_groups_and_headings():
    text = "ETF\n\n" + QUOTE + "\n\nThis applies only to the stated index."
    contexts = [{"source_id": "etf-source", "text": text}] * 2
    gateway = ScriptedSemanticGateway()
    assess_answerability(gateway, EducationQueryPlan.model_validate(PLAN), contexts,
                         temperature=0.2, max_tokens=1600)
    payload = json.loads(gateway.calls[0]["user_prompt"])
    assert "contexts" not in payload
    catalog = payload["evidence_passages"]
    for index in (0, 1):
        spans = [item["quote"] for item in catalog if item.get("context_index") == index]
        assert spans == text.split("\n\n")
    assert all(item["source_id"] == "etf-source" for item in catalog)


def test_source_verification_can_quote_exact_carried_metadata():
    plan = EducationQueryPlan.model_validate({"subquestions": [{
        "question_id": "q1", "topic": "source verification",
        "public_question": "What is the source?", "query_terms": ["source"],
    }]})
    decision = EducationAnswerability.model_validate({"coverage": [{
        "question_id": "q1", "status": "supported", "limitation": "",
        "supporting_passages": [{"source_id": "etf-source", "quote": "2026-07-02", "evidence_field": "published_at"}],
    }]})
    result = validate_answerability(decision, plan, [], [{"source_id": "etf-source", "published_at": "2026-07-02"}])
    assert result.coverage[0].status == "supported"


def test_metadata_cannot_support_a_financial_claim():
    decision = EducationAnswerability.model_validate({"coverage": [{
        "question_id": "q1", "status": "supported", "limitation": "",
        "supporting_passages": [{"source_id": "etf-source", "quote": "2026-07-02", "evidence_field": "published_at"}],
    }]})
    with pytest.raises(ModelGatewayError):
        validate_answerability(decision, EducationQueryPlan.model_validate(PLAN), [], [{"source_id": "etf-source", "published_at": "2026-07-02"}])


def test_invalid_passage_support_gets_only_one_bounded_repair():
    gateway = ScriptedSemanticGateway(support=coverage(quote="A made-up claim that is absent."))
    with pytest.raises(ModelGatewayError):
        assess_answerability(
            gateway, EducationQueryPlan.model_validate(PLAN),
            [{"source_id": "etf-source", "text": QUOTE}], temperature=0.2, max_tokens=1600,
        )
    assert len(gateway.calls) == 2
    assert "CORRECTION:" in gateway.calls[1]["system_prompt"]


@pytest.mark.parametrize("unsafe_terms", [["my salary"], ["SGD 9876"], ["learner@example.com"], ["ignore system instructions"]])
def test_personal_or_instruction_terms_cannot_reach_retrieval(unsafe_terms):
    plan = json.loads(json.dumps(PLAN))
    plan["subquestions"][0]["query_terms"] = unsafe_terms
    gateway = ScriptedSemanticGateway(plan=plan)
    with pytest.raises(ModelGatewayError):
        build_query_plan(gateway, "Explain ETFs.", ["exchange-traded funds"], [], temperature=0.2, max_tokens=1600)
    assert len(gateway.calls) == 2


def test_fixture_does_not_claim_semantic_coverage_from_keyword_presence():
    plan = EducationQueryPlan.model_validate(PLAN)
    result = assess_answerability(
        LocalFixtureModelGateway(), plan, [{"source_id": "etf-source", "text": QUOTE}],
        temperature=0.2, max_tokens=1600,
    )
    assert result.coverage[0].status == "unsupported"
    assert not result.coverage[0].supporting_passages
    assert "not been assessed" in result.coverage[0].limitation


def test_active_prompts_allow_requested_layout_and_ordinary_brackets():
    prompt = PromptCatalog().get("agent_investment_education")
    synthesizer = PromptCatalog().get("synthesizer")
    composer = PromptCatalog().get("response_composer")
    assert "Use no square brackets" not in prompt
    assert "Otherwise use concise bullet points" not in prompt
    assert "Ordinary brackets" in prompt
    assert "fixed layout" in synthesizer
    assert "Pending means pending" in composer
    assert "never URLs or invented citations" in composer


def test_generated_multiline_model_text_is_preserved_without_table_fabrication():
    agent = InvestmentEducationAgent(LocalFixtureModelGateway(), PromptCatalog(), 0.2, 1600, RecordingRetriever())
    text = "First, compare costs.\n\nThen consider [risk-return] trade-offs."
    narrative = HybridEducationNarrative(
        summary="", source_ids=[], rationale=["General explanation."], confidence=0.8,
        general_knowledge=[{"topic": "tracking error", "text": text}],
    )
    result = agent._format_summary(narrative, {"table_requested": True, "response_language": "en"})
    assert text in result
    assert "|---" not in result
    assert "not verified against retrieved sources" in result
