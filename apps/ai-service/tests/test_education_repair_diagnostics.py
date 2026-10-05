"""Precise repair feedback preserves the education scope and provenance boundaries."""

import json

import pytest

from app.agents.investment_education import InvestmentEducationAgent
from app.core.prompts import PromptCatalog
from app.core.schemas import HybridEducationNarrative
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.models.structured import generate_structured_response
from app.rag.retriever import LocalEducationRetriever

SOURCE = {
    "source_id": "bond-source", "title": "Public bond guide", "issuing_organization": "MAS",
    "canonical_url": "https://www.mas.gov.sg/bonds", "published_at": "2026-07-02",
    "document_version": "2026-07-02", "checksum": "sha256:" + "a" * 64,
    "corpus_version": "investment-education-sg@test-v1", "review_due_at": "2099-12-31",
}
EXPLANATION = "Convexity describes the curve in a bond's price response; duration is a local approximation."


def narrative(**fields):
    return HybridEducationNarrative(
        rationale=["Public conceptual explanation."], confidence=0.8, **fields,
    )


def agent():
    return InvestmentEducationAgent(
        LocalFixtureModelGateway(), PromptCatalog("v6"), 0.2, 1600, LocalEducationRetriever(),
    )


def grounding(**fields):
    return {"sources": [SOURCE], "fallback_topics": ["bonds"], "ordered_topics": [], **fields}


class ScriptedWriter:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(next(self.responses).model_dump(mode="json"))


@pytest.mark.parametrize("rejected_topic", ["bond convexity", "private-value@example.invalid"])
def test_one_repair_receives_exact_allowed_metadata_and_preserves_convexity_explanation(rejected_topic):
    first = narrative(general_knowledge=[{"topic": rejected_topic, "text": EXPLANATION}])
    corrected = narrative(general_knowledge=[{"topic": "bonds", "text": EXPLANATION}])
    writer = ScriptedWriter([first, corrected])
    evidence = grounding()
    result = generate_structured_response(
        writer, response_type=HybridEducationNarrative,
        system_prompt="PROMPT_ID: agent_investment_education\nReturn a permitted public explanation.",
        user_prompt=json.dumps({"grounding": evidence}), temperature=0.2, max_tokens=1600,
        validate_response=lambda value: agent()._validate_narrative(value, dict(evidence)),
    )
    assert result.general_knowledge[0].topic == "bonds"
    assert result.general_knowledge[0].text == EXPLANATION
    assert len(writer.calls) == 2
    feedback = json.loads(writer.calls[1]["user_prompt"])["correction_feedback"]["validation_issues"]
    assert "general_knowledge[0].topic" in feedback and '["bonds"]' in feedback
    assert "metadata labels" in feedback
    assert "Do not answer an excluded subject under a permitted label" in feedback
    assert rejected_topic not in feedback
    assert feedback in writer.calls[1]["system_prompt"]


@pytest.mark.parametrize("fields,location,message", [
    ({"general_knowledge": [{"topic": "bonds", "text": EXPLANATION}] * 2},
     "general_knowledge", "duplicate topic"),
    ({"summary": "A bond is a loan."}, "summary", "source_ids is empty"),
    ({"source_ids": ["bond-source"]}, "source_ids", "summary is empty"),
    ({"source_ids": ["invented-secret"]}, "source_ids", "carried approved IDs"),
    ({"general_knowledge": [{"topic": "bonds", "text": EXPLANATION + " [source:bond-source]"}]},
     "general_knowledge[0].text", "Permitted citation IDs for this field: []"),
    ({"general_knowledge": [{"topic": "bonds", "text": "According to the evidence, duration is local."}]},
     "general_knowledge[0].text", "attributes model-only claims"),
])
def test_provenance_error_identifies_specific_field_without_echoing_rejected_content(fields, location, message):
    with pytest.raises(ModelGatewayError) as failed:
        agent()._validate_narrative(narrative(**fields), grounding())
    assert location in str(failed.value) and message in str(failed.value)
    assert "invented-secret" not in str(failed.value)
    assert "According to the evidence" not in str(failed.value)


def test_unsupported_carried_source_names_only_the_semantically_supported_ids():
    with pytest.raises(ModelGatewayError) as failed:
        agent()._validate_narrative(
            narrative(summary="A bond is a loan. [source:bond-source]", source_ids=["bond-source"]),
            grounding(coverage_assessment="model_semantic_with_exact_quotes", coverage_source_ids=[]),
        )
    assert failed.value.code == "INVALID_EDUCATION_PROVENANCE"
    assert "Permitted supporting source IDs: []" in str(failed.value)
    assert 'set summary="" and source_ids=[]' in str(failed.value)


def test_option_error_identifies_order_and_the_actual_inconsistent_field():
    with pytest.raises(ModelGatewayError) as failed:
        agent()._validate_narrative(
            narrative(ordered_options=[{"topic": "shares", "sourced_text": "A share is ownership."}]),
            grounding(ordered_topics=["bonds"]),
        )
    assert failed.value.code == "INVALID_EDUCATION_OPTIONS"
    assert 'grounding.ordered_topics in order: ["bonds"]' in str(failed.value)
    assert "ordered_options[0].sourced_text and source_ids" in str(failed.value)


def test_invalid_topic_still_fails_after_only_one_repair():
    bad = narrative(general_knowledge=[{"topic": "bond convexity", "text": EXPLANATION}])
    writer = ScriptedWriter([bad, bad])
    with pytest.raises(ModelGatewayError) as failed:
        generate_structured_response(
            writer, response_type=HybridEducationNarrative,
            system_prompt="PROMPT_ID: agent_investment_education", user_prompt=json.dumps({"grounding": grounding()}),
            temperature=0.2, max_tokens=1600,
            validate_response=lambda value: agent()._validate_narrative(value, grounding()),
        )
    assert failed.value.code == "INVALID_EDUCATION_PROVENANCE"
    assert len(writer.calls) == 2
