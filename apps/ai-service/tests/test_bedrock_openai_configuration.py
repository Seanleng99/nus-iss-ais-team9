"""Direct OpenAI generation with independently governed Bedrock retrieval."""

from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.models.gateway import OpenAIModelGateway, create_model_gateway
from app.rag.ingestion import metadata_for_source
from app.rag.policy import BedrockPolicyRetriever, create_policy_retriever
from app.rag.retriever import BedrockEducationRetriever, RetrievalError, create_education_retriever


def deployed_settings(**overrides):
    values = {
        "_env_file": None, "APP_ENV": "demo", "AI_SERVICE_API_KEY": "synthetic-service-key-long-enough",
        "MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "synthetic-key", "MODEL_ID": "gpt-6-luna",
        "RAG_PROVIDER": "bedrock", "POLICY_RAG_PROVIDER": "bedrock",
        "EDUCATION_KNOWLEDGE_BASE_ID": "EDUCATKB12", "POLICY_KNOWLEDGE_BASE_ID": "POLICYKB12",
        "EDUCATION_CORPUS_VERSION": "investment-education-sg@2026-09-27.2",
        "POLICY_CORPUS_VERSION": "financial-coach-policy-sg@2026-10-09.1",
        "POLICY_RAG_MINIMUM_SCORE": 0.0,
    }
    return Settings(**{**values, **overrides})


def test_both_bedrock_factories_keep_generation_on_direct_openai():
    settings = deployed_settings()
    assert isinstance(create_model_gateway(settings), OpenAIModelGateway)
    assert isinstance(create_education_retriever(settings), BedrockEducationRetriever)
    policy = create_policy_retriever(settings)
    assert isinstance(policy, BedrockPolicyRetriever)
    assert len(policy.required_sources) == 3


@pytest.mark.parametrize("field", ["EDUCATION_KNOWLEDGE_BASE_ID", "POLICY_KNOWLEDGE_BASE_ID"])
@pytest.mark.parametrize("value", [None, "", "wrong-account/KB", "SHORT"])
def test_deployed_bedrock_requires_valid_target_ids(field, value):
    with pytest.raises(ValueError, match=field):
        deployed_settings(**{field: value})


@pytest.mark.parametrize("field", ["EDUCATION_CORPUS_VERSION", "POLICY_CORPUS_VERSION"])
def test_deployed_bedrock_rejects_fixture_pins(field):
    with pytest.raises(ValueError, match=field):
        deployed_settings(**{field: "corpus@local-fixture-v1"})


class PolicyClient:
    def __init__(self, retriever, *, missing=None, changed=None):
        from app.rag.local_policy import LocalDocumentPolicyRetriever

        approved = LocalDocumentPolicyRetriever()
        self.metadata = {source.source_id: metadata_for_source(
            approved.manifest, source, ingested_at=datetime.now(UTC),
        ).model_dump(mode="json", exclude_none=True) for source, _ in approved.documents}
        self.documents = {source.source_id: text for source, text in approved.documents}
        self.missing, self.changed = missing, changed
        self.requests = []

    def retrieve(self, **request):
        self.requests.append(request)
        filters = request["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"]["andAll"]
        source_id = next(item["equals"]["value"] for item in filters if item["equals"]["key"] == "source_id")
        if source_id == self.missing:
            return {"retrievalResults": []}
        metadata = dict(self.metadata[source_id])
        if source_id == self.changed:
            metadata["checksum"] = "sha256:" + "a" * 64
        return {"retrievalResults": [{
            "content": {"text": self.documents[source_id]}, "metadata": metadata, "score": 0.3,
        }]}


def test_policy_fetches_every_control_without_sending_personal_draft_to_aws():
    policy = create_policy_retriever(deployed_settings())
    client = PolicyClient(policy)
    policy._client = client
    results = policy.retrieve("Review Alice's account 123456 and SGD 9000 allocation")
    assert {chunk.source_id for chunk in results} == {source.source_id for source in policy.required_sources}
    assert len(client.requests) == 3
    assert all(request["retrievalQuery"]["text"] in {source.title for source in policy.required_sources}
               for request in client.requests)
    assert all("Alice" not in str(request) and "9000" not in str(request) for request in client.requests)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_policy_fails_closed_when_a_required_control_is_missing_or_changed(damage):
    policy = create_policy_retriever(deployed_settings())
    policy._client = PolicyClient(policy, **{damage: policy.required_sources[1].source_id})
    with pytest.raises(RetrievalError):
        policy.retrieve("Review a budget")


def test_bedrock_policy_pin_must_match_the_checked_in_approved_controls():
    with pytest.raises(ValueError, match="POLICY_CORPUS_VERSION"):
        create_policy_retriever(deployed_settings(POLICY_CORPUS_VERSION="policy@unreviewed"))
