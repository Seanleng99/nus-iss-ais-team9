"""Bounded offline workflow contracts for representative education questions.

The local fixture gateway and local fixture corpus verify routing, scope
preservation, citation provenance, and honest evidence gaps. They do not measure
the quality of answers from a live model.
"""

from __future__ import annotations

import json

import pytest

from app.core.config import Settings
from app.core.schemas import AgentName, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
from app.rag.policy import LocalPolicyRetriever
from app.rag.retriever import LocalEducationRetriever

_EDUCATION_CORPUS = "investment-education-sg@local-fixture-v1"
_APPROVED_SOURCE_IDS = {
    "cpf-beginners-guide-to-investing",
    "cpf-investment-scheme-guide",
    "moneysense-what-is-investing",
    "moneysense-managing-investment-risk",
    "moneysense-types-of-investments",
    "moneysense-guide-to-etfs",
    "moneysense-compound-interest",
    "moneysense-managing-money",
    "moneysense-managing-debt",
    "moneysense-investment-scams",
}


class RecordingLocalFixtureModelGateway(LocalFixtureModelGateway):
    """Capture requests while delegating every answer to the existing fixture."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return super().generate(**kwargs)


def _orchestrator() -> tuple[AgentOrchestrator, RecordingLocalFixtureModelGateway]:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        AI_SERVICE_API_KEY="synthetic-offline-test-key-12345",
        MODEL_PROVIDER="local_fixture",
        RAG_PROVIDER="local_fixture",
        POLICY_RAG_PROVIDER="local_fixture",
        PROMPT_SET_VERSION="v6",
    )
    gateway = RecordingLocalFixtureModelGateway()
    orchestrator = AgentOrchestrator(
        config=settings,
        gateway=gateway,
        education_retriever=LocalEducationRetriever(),
        policy_retriever=LocalPolicyRetriever(),
    )
    return orchestrator, gateway


def _assert_answer_contract(
    response,
    *,
    gateway: RecordingLocalFixtureModelGateway,
    question: str,
    expected_topics: tuple[str, ...],
    evidence_status: str,
    expected_source_ids: tuple[str, ...],
    answer_terms: tuple[tuple[str, ...], ...],
    record_investment_response,
    expected_unanswered_topics: tuple[str, ...] = (),
) -> None:
    # Record immediately so JUnit retains the actual fixture response on failure.
    record_investment_response(
        question,
        response.answer,
        source="Offline workflow (mock model and fixture retrieval)",
    )
    writer_calls = [
        call for call in gateway.calls
        if call["system_prompt"].startswith("PROMPT_ID: agent_investment_education")
    ]
    if expected_topics:
        assert writer_calls, f"investment education writer was not called: {question}"
        writer_payload = json.loads(writer_calls[-1]["user_prompt"])
        assert question in writer_payload["message"], (
            f"writer prompt lost the learner's question: {question}; "
            f"actual={writer_payload['message']}"
        )
    else:
        assert not writer_calls, f"unsupported topic reached the writer: {question}"

    education = next(
        (
            result
            for result in response.agent_results
            if result.agent == AgentName.INVESTMENT_EDUCATION
        ),
        None,
    )
    assert education is not None, f"auto-routing omitted investment education: {question}"
    assert AgentName.INVESTMENT_EDUCATION in response.selected_agents, (
        f"auto-routing did not select investment education: {question}; "
        f"selected={[agent.value for agent in response.selected_agents]}"
    )
    assert response.blocked is False, f"general education question was blocked: {question}"
    assert education.blocked is False, f"education agent was blocked: {question}"
    assert response.answer.strip(), f"workflow returned an empty answer: {question}"
    assert education.data.get("needs_input") is not True, (
        f"general education question unnecessarily needs input: {question}"
    )
    assert education.data.get("evidence_status") == evidence_status, (
        f"unexpected evidence status for {question}: "
        f"{education.data.get('evidence_status')}"
    )
    assert education.data.get("query_topics") == list(expected_topics), (
        f"canonical topics changed for {question}: {education.data.get('query_topics')}"
    )
    assert education.data.get("unanswered_topics", []) == list(expected_unanswered_topics), (
        f"unexpected evidence gaps for {question}: "
        f"{education.data.get('unanswered_topics')}"
    )

    response_source_ids = {source.source_id for source in response.sources}
    cited_source_ids = set(education.data.get("cited_source_ids") or [])
    assert set(expected_source_ids) <= response_source_ids, (
        f"expected approved sources missing for {question}: "
        f"expected={expected_source_ids}, actual={sorted(response_source_ids)}"
    )
    assert response_source_ids == cited_source_ids, (
        f"visible citations disagree with education citations for {question}: "
        f"visible={sorted(response_source_ids)}, cited={sorted(cited_source_ids)}"
    )
    assert response_source_ids <= _APPROVED_SOURCE_IDS, (
        f"workflow returned a citation outside the fixture corpus for {question}: "
        f"{sorted(response_source_ids - _APPROVED_SOURCE_IDS)}"
    )
    for source in response.sources:
        assert source.corpus_version == _EDUCATION_CORPUS, (
            f"unexpected corpus provenance for {question}: {source.source_id}"
        )
        assert source.canonical_url.startswith(
            ("https://www.cpf.gov.sg/", "https://www.moneysense.gov.sg/")
        ), f"unexpected source URL for {question}: {source.canonical_url}"
        assert source.checksum.startswith("sha256:")
        assert len(source.checksum) == len("sha256:") + 64
        assert source.canonical_url in response.answer, (
            f"citation metadata was not rendered in the answer for {question}: "
            f"{source.canonical_url}"
        )

    if evidence_status == "insufficient":
        assert response.sources == [], f"unsupported topic cited sources: {question}"
    else:
        assert "RAG knowledge base" in response.answer, (
            f"grounded answer omitted the RAG disclosure: {question}"
        )
        assert "no live web search" in response.answer, (
            f"answer omitted the freshness limitation: {question}"
        )

    answer = response.answer.casefold()
    for alternatives in answer_terms:
        assert any(term.casefold() in answer for term in alternatives), (
            f"answer omitted expected topic evidence {alternatives} for {question}: "
            f"{response.answer}"
        )
    for topic in expected_unanswered_topics:
        assert topic.casefold() in answer, (
            f"answer hid expected evidence gap {topic!r} for {question}: {response.answer}"
        )


BEGINNER_CASES = [
    pytest.param(
        "im new to investment, how do i start",
        ("investment basics",), "grounded", ("cpf-beginners-guide-to-investing",),
        (("time horizon", "diversification", "risk tolerance"),),
        id="beginner_B01_starting_out",
    ),
    pytest.param(
        "What is the difference between saving and investing?",
        ("saving vs investing",), "grounded", ("moneysense-what-is-investing",),
        (("saving",), ("investing",)),
        id="beginner_B02_saving_vs_investing",
    ),
    pytest.param(
        "Explain compound interest with a simple hypothetical example.",
        ("compound interest",), "grounded", ("moneysense-compound-interest",),
        (("compound interest",), ("principal", "earlier interest")),
        id="beginner_B03_compound_interest_example",
    ),
    pytest.param(
        "What is diversification, and can investments still lose value?",
        ("diversification",), "grounded",
        ("cpf-beginners-guide-to-investing", "moneysense-managing-investment-risk"),
        (("diversification",), ("lose value",)),
        id="beginner_B04_diversification_and_loss",
    ),
    pytest.param(
        "What are the main differences between shares and bonds?",
        ("shares", "bonds"), "grounded", ("moneysense-types-of-investments",),
        (("shares",), ("bonds",)),
        id="beginner_B05_shares_and_bonds",
    ),
    pytest.param(
        "What is an ETF, and what risks should a new investor understand?",
        ("exchange-traded funds",), "grounded", ("moneysense-guide-to-etfs",),
        (("exchange-traded funds",), ("risk",)),
        id="beginner_B06_etf_basics_and_risk",
    ),
    pytest.param(
        "What investment fees should a beginner look for?",
        ("investment fees",), "grounded", ("cpf-beginners-guide-to-investing",),
        (("fees",),),
        id="beginner_B07_investment_fees",
    ),
    pytest.param(
        "How do investment time horizon and risk tolerance relate to each other?",
        ("risk tolerance", "investment time horizon"), "grounded",
        ("moneysense-what-is-investing", "cpf-beginners-guide-to-investing"),
        (("time horizon",),),
        id="beginner_B08_horizon_and_risk_tolerance",
    ),
    pytest.param(
        "How can inflation affect money kept as cash?",
        ("inflation",), "grounded", ("cpf-beginners-guide-to-investing",),
        (("inflation",), ("cash", "purchase less")),
        id="beginner_B09_inflation_and_cash",
    ),
    pytest.param(
        "What reliable sources support your investment explanations, and how up to date are they?",
        ("source verification",), "grounded",
        ("cpf-beginners-guide-to-investing", "moneysense-what-is-investing"),
        (("captured document dates",), ("not live checks",)),
        id="beginner_B10_source_versions_and_freshness",
    ),
]


INTERMEDIATE_CASES = [
    pytest.param(
        "Compare ETFs and unit trusts by structure, costs and trading access.",
        ("funds", "exchange-traded funds"), "grounded",
        ("moneysense-types-of-investments", "moneysense-guide-to-etfs"),
        (("funds",), ("fees", "costs")),
        id="intermediate_I01_etfs_and_unit_trusts",
    ),
    pytest.param(
        "Explain the differences between market risk, credit risk and liquidity risk.",
        ("market risk", "credit risk", "liquidity risk"), "grounded",
        ("moneysense-managing-investment-risk",),
        (("market",), ("credit",), ("liquidity",)),
        id="intermediate_I02_risk_types",
    ),
    pytest.param(
        "How can currency risk affect an overseas ETF investment?",
        ("currency risk", "exchange-traded funds"), "grounded",
        ("moneysense-guide-to-etfs", "moneysense-managing-investment-risk"),
        (("exchange-traded funds",),),
        id="intermediate_I03_currency_risk",
    ),
    pytest.param(
        "How does dollar-cost averaging work, and what investment risks remain?",
        ("dollar-cost averaging",), "grounded", ("moneysense-managing-investment-risk",),
        (("dollar-cost averaging",), ("fixed sum",)),
        id="intermediate_I04_dollar_cost_averaging",
    ),
    pytest.param(
        "How do REITs generate investment income, and how does their liquidity differ from direct property?",
        ("real estate investment trusts", "liquidity", "investment income"), "grounded",
        ("moneysense-types-of-investments",),
        (("real estate investment trusts",), ("liquidity",)),
        id="intermediate_I05_reits_and_liquidity",
    ),
    pytest.param(
        "Compare Singapore Savings Bonds, treasury bills and fixed deposits at a conceptual level.",
        ("fixed deposits", "treasury bills", "Singapore Savings Bonds"), "grounded",
        ("cpf-beginners-guide-to-investing",),
        (("Singapore Savings Bonds",), ("treasury bills",), ("fixed deposits",)),
        id="intermediate_I06_cash_like_products",
    ),
    pytest.param(
        "How do ongoing fund fees affect net investment returns?",
        ("investment fees", "net returns fees"), "grounded",
        ("cpf-beginners-guide-to-investing",),
        (("fees",), ("returns",)),
        id="intermediate_I07_fees_and_net_returns",
    ),
    pytest.param(
        "How does liquidity risk differ from credit risk when comparing bonds?",
        ("credit risk", "liquidity risk", "bonds"), "grounded",
        ("moneysense-managing-investment-risk",),
        (("liquidity",), ("credit",)),
        id="intermediate_I08_bond_risks",
    ),
    pytest.param(
        "How does correlation affect diversification across investment assets?",
        ("diversification", "correlation"), "grounded",
        ("cpf-beginners-guide-to-investing", "moneysense-managing-investment-risk"),
        (("diversification",),),
        id="intermediate_I09_correlation_and_diversification",
    ),
    pytest.param(
        "Why can an ETF's return differ from its index, and what causes tracking error?",
        ("tracking error", "exchange-traded funds"), "grounded",
        ("moneysense-guide-to-etfs",),
        (("tracking error",), ("exchange-traded funds",)),
        id="intermediate_I10_tracking_error",
    ),
]


SPECIALIST_CASES = [
    pytest.param(
        "Compare cash-based physical ETFs and synthetic ETFs, including counterparty risk.",
        ("counterparty risk", "exchange-traded funds", "cash-based physical ETFs", "synthetic ETFs derivatives swaps"),
        "grounded", ("moneysense-guide-to-etfs",),
        (("counterparty risk",), ("fees",)),
        (),
        id="specialist_S01_physical_and_synthetic_etfs",
    ),
    pytest.param(
        "Explain why an ETF's traded price may differ from NAV and how market-maker liquidity matters.",
        ("exchange-traded funds", "net asset value", "traded price demand supply", "liquidity"),
        "grounded", ("moneysense-guide-to-etfs",),
        (("liquidity",), ("exchange-traded",)),
        (),
        id="specialist_S02_nav_and_market_liquidity",
    ),
    pytest.param(
        "What securities lending risks can arise in physical ETFs?",
        ("exchange-traded funds", "securities lending", "cash-based physical ETFs"),
        "grounded", ("moneysense-guide-to-etfs",),
        (("risk",), ("exchange-traded",)),
        (),
        id="specialist_S03_securities_lending_topic_contract",
    ),
    pytest.param(
        "Distinguish tracking error from tracking difference when evaluating ETFs, and identify any knowledge gaps.",
        ("tracking difference", "tracking error", "exchange-traded funds"),
        "grounded", ("moneysense-guide-to-etfs",),
        (("tracking error",),),
        (),
        id="specialist_S04_tracking_difference_topic_contract",
    ),
    pytest.param(
        "Explain bond duration and how it relates to interest-rate sensitivity; state any limits in your sources.",
        ("bond duration",), "insufficient", (),
        (("approved knowledge base does not contain enough information",), ("bond duration",)),
        ("bond duration",),
        id="specialist_S05_bond_duration_evidence_gap",
    ),
    pytest.param(
        "Compare zero-coupon bonds and coupon bonds, making clear where evidence is unavailable.",
        ("bonds", "zero-coupon bonds"), "partial", ("moneysense-types-of-investments",),
        (("bonds",), ("approved knowledge base does not contain enough information",), ("zero-coupon bonds",)),
        ("zero-coupon bonds",),
        id="specialist_S06_zero_coupon_partial_evidence_gap",
    ),
    pytest.param(
        "Explain ETF structure and identify whether your sources cover cross-border tax treatment.",
        ("exchange-traded funds",), "partial", ("moneysense-guide-to-etfs",),
        (("exchange-traded funds",), ("approved knowledge base does not contain enough information",), ("tax treatment",)),
        ("tax treatment",),
        id="specialist_S07_tax_treatment_partial_evidence_gap",
    ),
    pytest.param(
        "What source versions support the CPF Investment Scheme explanation, and can they establish current rates?",
        ("CPF Investment Scheme",), "partial", ("cpf-investment-scheme-guide",),
        (("CPFIS",), ("approved knowledge base does not contain enough information",), ("live market data",)),
        ("live market data",),
        id="specialist_S08_current_CPFIS_rates_evidence_gap",
    ),
    pytest.param(
        "Explain options trading as an investment concept and identify gaps in your approved knowledge base.",
        (), "insufficient", (),
        (("approved knowledge base does not contain enough information",), ("options trading",), ("outside this version's supported",)),
        ("options trading",),
        id="specialist_S09_options_trading_scope_limit",
    ),
    pytest.param(
        "Explain zero-coupon bonds and identify any limits in your sources.",
        ("zero-coupon bonds",), "insufficient", (),
        (("approved knowledge base does not contain enough information",), ("zero-coupon bonds",)),
        ("zero-coupon bonds",),
        id="specialist_S10_zero_coupon_evidence_gap",
    ),
]

@pytest.mark.parametrize(
    "question,expected_topics,evidence_status,expected_source_ids,answer_terms",
    BEGINNER_CASES,
)
def test_beginner_investor_functional(
    question,
    expected_topics,
    evidence_status,
    expected_source_ids,
    answer_terms,
    record_investment_response,
):
    orchestrator, gateway = _orchestrator()
    response = orchestrator.handle(
        CoachRequest(
            user_id="synthetic-investment-learner",
            session_id="synthetic-beginner-functional",
            message=question,
            response_locale="en",
        )
    )
    _assert_answer_contract(
        response,
        gateway=gateway,
        question=question,
        expected_topics=expected_topics,
        evidence_status=evidence_status,
        expected_source_ids=expected_source_ids,
        answer_terms=answer_terms,
        record_investment_response=record_investment_response,
    )


@pytest.mark.parametrize(
    "question,expected_topics,evidence_status,expected_source_ids,answer_terms",
    INTERMEDIATE_CASES,
)
def test_intermediate_investor_functional(
    question,
    expected_topics,
    evidence_status,
    expected_source_ids,
    answer_terms,
    record_investment_response,
):
    orchestrator, gateway = _orchestrator()
    response = orchestrator.handle(
        CoachRequest(
            user_id="synthetic-investment-learner",
            session_id="synthetic-intermediate-functional",
            message=question,
            response_locale="en",
        )
    )
    _assert_answer_contract(
        response,
        gateway=gateway,
        question=question,
        expected_topics=expected_topics,
        evidence_status=evidence_status,
        expected_source_ids=expected_source_ids,
        answer_terms=answer_terms,
        record_investment_response=record_investment_response,
    )


@pytest.mark.parametrize(
    "question,expected_topics,evidence_status,expected_source_ids,answer_terms,expected_unanswered_topics",
    SPECIALIST_CASES,
)
def test_specialist_investor_functional(
    question,
    expected_topics,
    evidence_status,
    expected_source_ids,
    answer_terms,
    expected_unanswered_topics,
    record_investment_response,
):
    orchestrator, gateway = _orchestrator()
    response = orchestrator.handle(
        CoachRequest(
            user_id="synthetic-investment-learner",
            session_id="synthetic-specialist-functional",
            message=question,
            response_locale="en",
        )
    )
    _assert_answer_contract(
        response,
        gateway=gateway,
        question=question,
        expected_topics=expected_topics,
        evidence_status=evidence_status,
        expected_source_ids=expected_source_ids,
        answer_terms=answer_terms,
        record_investment_response=record_investment_response,
        expected_unanswered_topics=expected_unanswered_topics,
    )
