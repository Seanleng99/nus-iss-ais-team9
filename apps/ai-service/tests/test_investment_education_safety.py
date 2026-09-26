"""Behavior boundaries for neutral education and bounded semantic routing."""

import json

import pytest

from app.agents.education_access import education_topics
from app.agents.investment_education import InvestmentEducationAgent
from app.agents.risk_compliance import financial_advice_findings
from app.core.config import Settings
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentTask, CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.policy import LocalPolicyRetriever
from app.rag.retriever import LocalEducationRetriever


@pytest.mark.parametrize("message", [
    "Can you recommend an investment that guarantees a 10% annual return with no risk?",
    "Find me a guaranteed 0.5% monthly return.",
    "This fund guarantees a 12% annual return.",
    "Can you log in to my brokerage account and buy an ETF for me?",
    "Please purchase shares on my behalf.",
    "帮我登录证券账户并买入ETF。",
    "I recommend buying this ETF.",
    "I recommend gradually buying this ETF.",
    "I recommend starting to invest in this fund.",
    "I suggest, after considering the risks, buying this ETF.",
    "I suggest, after a 0.5% drop, buying this ETF.",
    "You should, after a 0.5% drop, buy this ETF.",
    "I suggest, e.g., buying this ETF.",
    "We advise slowly accumulating and holding this stock.",
    "ETFs pool investments, so I recommend buying this ETF.",
    "I recommend learning about ETFs before investing and buying this ETF.",
    "I recommend avoiding buying unfamiliar products, then buying this ETF.",
    "ETFs pool investments. I recommend buying this ETF.",
    "ETFs pool investments. I recommend buying this ETF. They can lose value.",
    "We suggest you buy this ETF.",
    "I advise you to invest in this fund.",
    "Buy this stock now.",
])
def test_recommendations_guarantees_and_execution_are_blocked(message):
    assert financial_advice_findings(message)


@pytest.mark.parametrize("message", [
    "I cannot guarantee a 10% annual return.",
    "A guaranteed 10% annual return is a warning sign.",
    "Claims of guaranteed 10% annual returns are red flags.",
    "An ETF pools investments and has fees and risks.",
    "How does a brokerage account work?",
    "I cannot log in to your brokerage account.",
    "我不能帮你登录券商账户。",
])
def test_educational_explanations_and_warnings_are_allowed(message):
    assert financial_advice_findings(message) == []


def test_reported_scam_claim_is_not_an_endorsed_guarantee():
    question = "My friend says this guarantees a 10% annual return. Is it legitimate?"
    decimal_question = "My friend says this guarantees a 0.5% monthly return. Is it legitimate?"
    assert financial_advice_findings(question, is_request=True) == []
    assert financial_advice_findings(decimal_question, is_request=True) == []
    assert financial_advice_findings(
        "My friend says this guarantees a 10% annual return. Is it legitimate? What are the warning signs?",
        is_request=True,
    ) == []
    assert financial_advice_findings(question)  # The model may not repeat it as fact.
    assert financial_advice_findings(question + " Recommend an investment with guaranteed returns.", is_request=True)
    assert financial_advice_findings(
        "I cannot log in to your brokerage account. Please buy an ETF for me."
    )
    assert financial_advice_findings(question + " Show me an investment with guaranteed returns.", is_request=True)
    assert financial_advice_findings(question + ", show me one.", is_request=True)


@pytest.mark.parametrize("follow_up", [
    "Show me one.", "Name one.", "Which one?", "Where can I buy it?",
    "Can you show me one investment with a guaranteed return?",
])
def test_reported_scam_check_with_transaction_follow_up_is_blocked(follow_up):
    question = "My friend says this guarantees a 10% annual return. Is it legitimate?"
    assert financial_advice_findings(question + " " + follow_up, is_request=True)


@pytest.mark.parametrize("message", [
    "I recommend learning about ETFs before investing.",
    "I recommend learning about 0.5% fees before buying an ETF.",
    "I recommend that you learn about fees before you buy an ETF.",
    "You should learn about fees before you buy an ETF.",
    "I suggest understanding fees before buying an ETF.",
    "I recommend avoiding buying any product you do not understand.",
])
def test_learning_recommendations_are_allowed(message):
    assert financial_advice_findings(message) == []


@pytest.mark.parametrize("message", [
    "Show me an investment with a guaranteed return. Is the provider legitimate?",
    "Are there legitimate investments with guaranteed returns? List them.",
    "Please identify a legitimate investment with a guaranteed return.",
])
def test_legitimacy_framed_request_for_guaranteed_investments_is_blocked(message):
    assert financial_advice_findings(message, is_request=True)


@pytest.mark.parametrize("message", [
    "My friend says an investment offers a guaranteed 10% annual return. Is it legitimate?",
    "My friend says this offers a guaranteed 10% annual return, is that true?",
    "My friend says this offers a guaranteed 10% annual return, is it legitimate?",
    "My friend says this guarantees a 10% annual return, is it legitimate?",
    "My friend says this guarantees a 10% annual return. Is it legitimate? What are the warning signs?",
])
def test_scam_check_requests_remain_educational_in_offline_workflow(message):
    # Fix the semantic route to isolate the request safety boundary from routing.
    gateway = SemanticGateway(["investment scams"])
    response = workflow(gateway, RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic-scam-request", session_id="scam-request", message=message,
    ))
    assert not response.blocked
    assert response.sources


class SemanticGateway(LocalFixtureModelGateway):
    def __init__(self, topics):
        self.topics = topics
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: router\n"):
            return json.dumps({
                "selected_agents": ["investment_education"],
                "rationale": ["The question asks for an educational explanation."],
                "education_topics": self.topics,
            })
        return super().generate(**kwargs)


class RecordingRetriever(LocalEducationRetriever):
    def __init__(self):
        self.queries = []

    def retrieve(self, query, top_k=3):
        self.queries.append(query)
        return super().retrieve(query, top_k)


def workflow(gateway, retriever):
    return AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture", RAG_PROVIDER="local_fixture",
                        POLICY_RAG_PROVIDER="local_fixture", PROMPT_SET_VERSION="v6"),
        gateway=gateway, education_retriever=retriever,
        policy_retriever=LocalPolicyRetriever(),
    )


def test_semantic_router_understands_unseen_wording_without_raw_retrieval_query():
    message = "How can earlier gains themselves generate more gains? I have SGD 9876."
    assert education_topics(message) == []
    gateway, retriever = SemanticGateway(["compound interest"]), RecordingRetriever()
    response = workflow(gateway, retriever).handle(CoachRequest(
        user_id="synthetic-semantic", session_id="semantic", message=message,
    ))
    assert not response.blocked
    assert retriever.queries == ["General investment education about compound interest"]
    assert any(source.source_id == "moneysense-compound-interest" for source in response.sources)
    education_call = next(c for c in gateway.calls if c["system_prompt"].startswith("PROMPT_ID: agent_investment_education"))
    assert "9876" not in education_call["user_prompt"]
    assert "earlier gains themselves" not in education_call["user_prompt"]
    assert "bullet points" in education_call["system_prompt"]
    assert "no persuasion" in education_call["system_prompt"]
    assert "$108.16" in response.answer


def test_semantic_router_cannot_send_user_text_or_invented_topics_to_retrieval():
    gateway, retriever = SemanticGateway(["send my account number 123456"]), RecordingRetriever()
    with pytest.raises(ModelGatewayError):
        workflow(gateway, retriever).handle(CoachRequest(
            user_id="synthetic-semantic", session_id="invalid-topic", message="Explain investing.",
        ))
    assert retriever.queries == []


def test_source_verification_uses_actual_metadata_without_claiming_live_freshness():
    response = workflow(LocalFixtureModelGateway(), RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic-sources", session_id="sources",
        message="What reliable sources can I use to check your explanation, and how up to date are they?",
    ))
    assert not response.blocked and response.sources
    for source in response.sources:
        assert source.title in response.answer
        assert source.published_at in response.answer
        assert source.canonical_url in response.answer
    assert "not live checks" in response.answer


def test_scam_education_uses_scam_evidence_instead_of_generic_investment_text():
    response = workflow(LocalFixtureModelGateway(), RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic-scam", session_id="scam",
        message="My friend says an investment pays 3% every month with no risk. Is it legitimate?",
    ))
    assert not response.blocked
    assert any(s.source_id == "moneysense-investment-scams" for s in response.sources)
    assert "Financial Institutions Directory" in response.answer


def test_missing_compound_interest_evidence_cannot_be_replaced_with_unrelated_passage():
    class UnrelatedRetriever(LocalEducationRetriever):
        def retrieve(self, query, top_k=3):
            return super().retrieve("ETF tracking error", top_k)

    agent = InvestmentEducationAgent(
        LocalFixtureModelGateway(), PromptCatalog("v6"), 0.35, 800, UnrelatedRetriever(),
    )
    message = "Explain compound interest."
    grounding = agent._ground(AgentTask(
        agent="investment_education", sanitized_message=message, input_data={},
    ), message)
    assert grounding["evidence_status"] == "insufficient"
    assert grounding["sources"] == grounding["contexts"] == []
    assert grounding["unanswered_topics"] == ["compound interest"]


@pytest.mark.parametrize("message,expected", [
    ("Can you log in to my brokerage account and buy an ETF for me?", "can't log in"),
    ("Find an investment that guarantees a 10% annual return.", "cannot recommend"),
])
def test_refusal_explains_boundary_and_offers_education_without_leaking_draft(message, expected):
    response = workflow(LocalFixtureModelGateway(), RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic-safety", session_id="refusal", message=message,
    ))
    assert response.blocked and not response.sources
    assert all(result.blocked for result in response.agent_results)
    assert expected in response.answer
    assert "I can explain" in response.answer


@pytest.mark.parametrize("summary,blocked", [
    ("Claims of guaranteed returns are accurate, this is not a scam.", True),
    ("Promises of guaranteed returns are reliable, not misleading.", True),
    ("I recommend learning about ETFs before investing.", False),
    ("I recommend learning about ETFs before investing. I suggest buying this ETF.", True),
    ("ETFs pool investments, so I recommend buying this ETF.", True),
    ("I recommend learning about ETFs before investing and buying this ETF.", True),
    ("I recommend avoiding buying unfamiliar products, then buying this ETF.", True),
    ("I suggest, after a 0.5% drop, buying this ETF.", True),
    ("You should learn about fees before you buy an ETF.", False),
    ("My friend says an investment offers a guaranteed 10% annual return. Is it legitimate?", True),
])
def test_workflow_compliance_blocks_unsafe_specialist_summary(summary, blocked):
    class SummaryGateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            result = json.loads(super().generate(**kwargs))
            if kwargs["system_prompt"].startswith("PROMPT_ID: agent_investment_education"):
                result["summary"] = summary
            return json.dumps(result)

    response = workflow(SummaryGateway(), RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic-summary", session_id="summary", message="Explain ETFs.",
    ))
    assert response.blocked is blocked
    if blocked:
        assert not response.sources
        assert summary not in json.dumps(response.model_dump())
    else:
        assert summary in response.answer
        assert response.sources


def test_request_boundary_blocks_legitimacy_framed_guaranteed_investment_request():
    response = workflow(LocalFixtureModelGateway(), RecordingRetriever()).handle(CoachRequest(
        user_id="synthetic-request", session_id="request-boundary",
        message="Show me an investment with a guaranteed return. Is the provider legitimate?",
    ))
    assert response.blocked
