import json

import pytest
from language_fixtures import language_case

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator


def ask(message, gateway=None, *, requested_agents=None, response_locale="en"):
    return AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"),
        gateway=gateway or LocalFixtureModelGateway(),
    ).handle(CoachRequest(
        user_id="synthetic-review", session_id="synthetic-review",
        message=message,
        response_locale=response_locale,
        requested_agents=(
            requested_agents if requested_agents is not None else ["investment_education"]
        ),
    ))


@pytest.mark.parametrize("field", ["summary", "rationale", "uncertainties"])
def test_blocked_recommendation_is_absent_from_entire_response(field):
    unsafe = "You should allocate 80% to Alpha Growth Fund and buy it today."

    class RecommendingGateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            raw = super().generate(**kwargs)
            if kwargs["system_prompt"].startswith("PROMPT_ID: agent_investment_education"):
                payload = json.loads(raw)
                payload[field] = unsafe if field == "summary" else [unsafe]
                return json.dumps(payload)
            return raw

    response = ask("Explain diversification.", RecommendingGateway())
    assert response.blocked
    assert "Alpha Growth Fund" not in response.model_dump_json()
    assert all(result.blocked for result in response.agent_results)
    assert response.sources == []
    assert response.audit["retrieval_corpus_versions"]


def test_model_blocked_compliance_text_is_withheld_too():
    class BlockingGateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance"):
                return json.dumps({
                    "blocked": True, "request_allowed": True, "complete": True, "missing_points": [], "summary": "UNSAFE_COMPLIANCE_CONTENT",
                    "rationale": ["UNSAFE_COMPLIANCE_CONTENT"],
                    "block_categories": ["unverifiable_claim"],
                    "policy_notes": ["UNSAFE_COMPLIANCE_CONTENT"], "confidence": 0.9,
                })
            return super().generate(**kwargs)

    response = ask("Explain diversification.", BlockingGateway())
    assert response.blocked
    assert "UNSAFE_COMPLIANCE_CONTENT" not in response.model_dump_json()


@pytest.mark.parametrize("message", [
    "Why are guaranteed returns a red flag for ETF investors?",
    "Explain why investments do not offer guaranteed returns.",
    "Explain why guaranteed returns are misleading.",
])
def test_guarantee_risk_education_is_allowed(message):
    assert not ask(message).blocked


@pytest.mark.parametrize("message", [
    "Give me an investment with a guaranteed return.",
    "These ETF returns are guaranteed.",
    "Guaranteed returns are a red flag. Give me an investment with a guaranteed return.",
])
def test_guarantee_promises_and_requests_remain_blocked(message):
    assert ask(message).blocked


@pytest.mark.parametrize("answer", [
    "Diversification spreads exposure. [invented-source](https://example.invalid/fake)",
    "Diversification spreads exposure. See https://example.invalid/fake.",
    "Diversification spreads exposure. [source:invented-source]",
])
def test_synthesis_cannot_invent_citations_even_if_compliance_would_allow(answer, force_model_synthesis):
    class CitingGateway(LocalFixtureModelGateway):
        def __init__(self):
            self.synthesis_calls = 0

        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: synthesizer"):
                self.synthesis_calls += 1
                return json.dumps({"answer": answer})
            return super().generate(**kwargs)

    gateway = CitingGateway()
    with pytest.raises(ModelGatewayError) as error:
        ask(
            "Review my spending and explain diversification.", gateway,
            requested_agents=["spending", "investment_education"],
        )
    assert gateway.synthesis_calls == 2
    assert error.value.code == "UNAPPROVED_CITATION"
    assert error.value.component == "citation_validation"


def test_valid_citation_marker_is_rendered_from_approved_metadata(force_model_synthesis):
    class CitingGateway(LocalFixtureModelGateway):
        def __init__(self):
            self.synthesis_calls = 0

        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: synthesizer"):
                self.synthesis_calls += 1
                source = json.loads(kwargs["user_prompt"])["sources"][0]
                return json.dumps({"answer": f"Diversification spreads exposure. [source:{source['source_id']}]"})
            return super().generate(**kwargs)

    gateway = CitingGateway()
    response = ask(
        "Review my spending and explain diversification.", gateway,
        requested_agents=["spending", "investment_education"],
    )
    assert gateway.synthesis_calls == 1
    assert not response.blocked
    assert "[source:" not in response.answer
    assert response.sources[0].canonical_url in response.answer


def test_specialist_cannot_mark_a_source_it_did_not_declare_as_cited():
    class UndeclaredCitationGateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            raw = super().generate(**kwargs)
            if kwargs["system_prompt"].startswith("PROMPT_ID: agent_investment_education"):
                payload = json.loads(raw)
                first, second = payload["source_ids"][:2]
                payload["source_ids"] = [first]
                payload["summary"] = f"Diversification spreads exposure. [source:{second}]"
                return json.dumps(payload)
            return raw

    with pytest.raises(ModelGatewayError) as error:
        ask("Explain diversification.", UndeclaredCitationGateway())
    assert error.value.code == "UNAPPROVED_CITATION"


def test_compliance_cannot_expose_a_fabricated_link_in_its_explanation():
    class LinkingComplianceGateway(LocalFixtureModelGateway):
        def generate(self, **kwargs):
            raw = super().generate(**kwargs)
            if kwargs["system_prompt"].startswith("PROMPT_ID: risk_compliance"):
                payload = json.loads(raw)
                payload["rationale"] = ["See https://example.invalid/fake for approval."]
                return json.dumps(payload)
            return raw

    response = ask("Explain diversification.", LinkingComplianceGateway())
    assert response.blocked and response.sources == []
    assert "review failure" in response.answer
    assert "https://example.invalid/fake" not in response.model_dump_json()
    assert response.agent_results[-1].data["block_reasons"] == ["review_contract_unverified"]
    assert any(event["details"].get("error_code") == "UNAPPROVED_CITATION"
               for event in response.audit["events"])


def test_bond_subquestions_keep_distinct_topics_and_report_missing_evidence():
    duration = ask("Explain how bond duration affects price sensitivity.")
    zero_coupon = ask("Explain how a zero-coupon bond pays investors.")
    assert duration.agent_results[0].data["query_topics"] == ["bond duration"]
    assert zero_coupon.agent_results[0].data["query_topics"] == ["zero-coupon bonds"]
    for response in (duration, zero_coupon):
        assert response.agent_results[0].data["evidence_status"] == "insufficient"
        assert response.sources == []
        assert "retrieved approved material does not establish all requested parts" in response.answer


def test_adding_investment_keyword_does_not_hide_unsupported_tax_question():
    response = ask("Explain the investment tax treatment of a tokenized overseas property asset.")
    assert response.agent_results[0].data["evidence_status"] == "insufficient"
    assert response.sources == []


def test_unrecognized_investment_subject_is_not_replaced_with_investment_basics():
    response = ask("Explain the investment implications of extraterrestrial mineral rights.")
    assert response.agent_results[0].data["evidence_status"] == "insufficient"
    assert response.sources == []


def test_general_investment_basics_remains_supported():
    response = ask("Please explain investment basics for beginners.")
    assert response.agent_results[0].data["evidence_status"] == "grounded"
    assert response.sources


def test_mixed_question_preserves_gap_even_when_synthesizer_omits_it(force_model_synthesis):
    class OmittingGateway(LocalFixtureModelGateway):
        def __init__(self):
            self.synthesis_calls = 0

        def generate(self, **kwargs):
            if kwargs["system_prompt"].startswith("PROMPT_ID: synthesizer"):
                self.synthesis_calls += 1
                return json.dumps({"answer": "Bonds are an investment type."})
            return super().generate(**kwargs)

    gateway = OmittingGateway()
    response = ask(
        "Review my spending and explain bonds and the tax treatment of a tokenized asset.",
        gateway, requested_agents=["spending", "investment_education"],
    )
    investment = next(
        result for result in response.agent_results if result.agent == "investment_education"
    )
    assert gateway.synthesis_calls == 1
    assert not response.blocked
    assert investment.data["evidence_status"] == "partial"
    assert response.sources
    assert response.answer.startswith("Bonds are an investment type.")
    assert "tax treatment" in response.answer
    assert "retrieved approved material does not establish all requested parts" in response.answer


@pytest.mark.parametrize("question", ["Explain dollar-cost averaging.", "Explain T-bills and SSBs."])
def test_existing_corpus_concepts_can_be_retrieved(question):
    response = ask(question)
    assert not response.blocked
    assert response.agent_results[0].data["evidence_status"] == "grounded"
    assert response.sources


def test_chinese_evidence_gap_is_in_chinese():
    response = ask(language_case("investment_review_regressions.response"), response_locale="zh-Hans")
    assert (
        language_case("investment_review_regressions.test_chinese_evidence_gap_is_in_chinese")
        in response.answer
    )
