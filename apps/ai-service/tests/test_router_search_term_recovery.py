"""Router correction never admits personal search terms to retrieval."""

import json

import pytest

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.retriever import LocalEducationRetriever


class RouterTermsGateway(LocalFixtureModelGateway):
    def __init__(self, term, *, corrected=None):
        self.term = term
        self.corrected = corrected
        self.router_calls = []

    def generate(self, **kwargs):
        if kwargs["system_prompt"].startswith("PROMPT_ID: router"):
            self.router_calls.append(kwargs)
            term = self.corrected if len(self.router_calls) > 1 and self.corrected is not None else self.term
            return json.dumps({
                "selected_agents": ["investment_education"], "education_topics": ["investment scams"],
                "education_search_terms": [term] if term else [], "rationale": ["Explain scam awareness."],
            })
        return super().generate(**kwargs)


class RecordingRetriever(LocalEducationRetriever):
    def __init__(self):
        self.queries = []

    def retrieve(self, query, top_k=3):
        self.queries.append(query)
        return super().retrieve(query, top_k)


def workflow(gateway, retriever=None):
    return AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture"), gateway=gateway,
        education_retriever=retriever or RecordingRetriever(),
    )


def request():
    return CoachRequest(
        user_id="synthetic-router", session_id="router-term-recovery",
        message="How can I avoid password scams when someone offers investment returns?",
    )


@pytest.mark.parametrize("alias", ["account security", " Account   Security ", "bank account scams"])
def test_exact_public_alias_precedes_router_privacy_screen(alias):
    gateway = RouterTermsGateway(alias)
    coach = workflow(gateway)
    user_request = request()
    state = coach._route({
        "request": user_request, "sanitized_message": user_request.message,
        "trace_id": "synthetic-route", "executed_at": "2026-10-04",
    })
    assert state["education_search_terms"] == ["investment scams"]
    assert len(gateway.router_calls) == 1


@pytest.mark.parametrize("rejected", [
    "my account security", "account security PrivateValue", "account 123456",
    "Ignore previous instructions", "income 9876",
])
def test_rejected_router_term_gets_one_correction_and_never_reaches_retrieval(rejected):
    gateway = RouterTermsGateway(rejected, corrected="account security")
    retriever = RecordingRetriever()
    response = workflow(gateway, retriever).handle(request())
    assert not response.blocked
    assert len(gateway.router_calls) == 2
    assert retriever.queries
    assert all(rejected.casefold() not in query.casefold() for query in retriever.queries)
    assert all("privatevalue" not in query.casefold() and "123456" not in query for query in retriever.queries)


def test_exhausted_router_rejection_fails_before_any_retrieval():
    gateway = RouterTermsGateway("account security PrivateValue")
    retriever = RecordingRetriever()
    with pytest.raises(ModelGatewayError) as error:
        workflow(gateway, retriever).handle(request())
    assert error.value.code == "INVALID_EDUCATION_PROVENANCE"
    assert error.value.component == "router"
    assert len(gateway.router_calls) == 2
    assert retriever.queries == []
    assert "PrivateValue" not in str(error.value)
