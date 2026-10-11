import json

import boto3
import pytest
from fastapi.testclient import TestClient

from app.core.action_composition import ActionCompositionRequest, compose_action
from app.core.config import Settings
from app.main import app
from app.models.gateway import BedrockModelGateway, LocalFixtureModelGateway
from app.orchestrator import AgentOrchestrator
from app.rag.retriever import RetrievalError


class ComposerGateway:
    def __init__(self, *, grounded=True, blocked=False, citation=False, referents=None):
        self.requests = []
        self.grounded = grounded
        self.blocked = blocked
        self.citation = citation
        self.referents = referents or []

    def generate(self, **kwargs):
        role = kwargs["system_prompt"].splitlines()[0]
        self.requests.append((role, json.loads(kwargs["user_prompt"])))
        if role == "PROMPT_ID: response_composer":
            return json.dumps({"answer": "Your change is ready for confirmation.\n\n"
                "| Savings | Explanation |\n|---|---|\n| SGD 200 | A planned monthly allocation. |"
                + (" [source:invented-source]" if self.citation else ""), "referents": self.referents})
        if role == "PROMPT_ID: action_grounding_review":
            return json.dumps({"faithful_to_outcomes": self.grounded,
                "unsupported_claims": [] if self.grounded else ["A pending plan was claimed as saved."],
                "omitted_requested_parts": []})
        return json.dumps({"blocked": self.blocked, "summary": "Policy reviewed.",
            "rationale": ["The request and grounded response were checked."],
            "confidence": 1.0, "policy_notes": ["The draft contains an unverifiable claim."] if self.blocked else [],
            "block_categories": ["unverifiable_claim"] if self.blocked else []})


def payload():
    return ActionCompositionRequest.model_validate({
        "request": {"user_id": "user", "session_id": "chat",
            "message": "Set aside 200 for savings and explain the plan in a table.",
            "snapshot": {"preferences": {"preferred_style": "brief", "secret": "drop-me"}}},
        "response": {"session_id": "chat", "selected_agents": ["budget"],
            "answer": "Preview: savings SGD 200. Confirm budget to save; nothing saved yet.",
            "agent_results": [{"agent": "budget", "summary": "A savings allocation is a plan, not a savings balance.",
                "data": {"budget_draft": {"savings_amount": 200}, "savings": 200}}],
            "disclaimers": [], "audit": {"trace_id": "trace"}},
        "outcomes": [{"operation": "budget", "status": "preview",
            "text": "Preview: savings SGD 200. Confirm budget to save; nothing saved yet."}],
    })


def service(gateway):
    return AgentOrchestrator(config=Settings(MODEL_PROVIDER="local_fixture", _env_file=None), gateway=gateway)


def test_post_action_model_calls_apply_the_same_privacy_boundary():
    request = payload()
    marker = "composition-private@example.com"
    request.request.message += " Contact " + marker
    request.request.snapshot.preferences["preferred_style"] = "Contact " + marker
    request.outcomes[0].text += " Contact " + marker
    request.response.agent_results[0].summary += " Contact " + marker
    from app.core.schemas import SourceCitation
    request.response.sources.append(SourceCitation(source_id="approved", title="Contact " + marker,
        issuing_organization="Synthetic", canonical_url="https://example.com/education",
        published_at="2026-10-10", document_version="1", checksum="sha256:" + "a" * 64,
        corpus_version="test", review_due_at="2099-12-31"))
    gateway = ComposerGateway()
    result = compose_action(request, service(gateway))
    assert result.audit["post_action_composed"]
    assert len(gateway.requests) == 3
    assert marker not in json.dumps(gateway.requests)


def test_same_draft_bearing_specialist_and_sanitized_preferences_reach_composer():
    gateway = ComposerGateway()
    result = compose_action(payload(), service(gateway))
    assert result.audit["post_action_composed"] is True
    assert "| Savings |" in result.answer
    sent = gateway.requests[0][1]
    assert sent["preferences"] == {"preferred_style": "brief"}
    assert sent["reviewed_specialists"][0]["data"]["budget_draft"] == {"savings_amount": 200}
    assert sent["authoritative_outcomes"][0]["status"] == "preview"
    assert result.audit["model_call_count"] == 3
    assert gateway.requests[-1][1]["agent_results"][-1]["data"]["authoritative_outcomes"]


@pytest.mark.parametrize("settings", [{"grounded": False}, {"blocked": True}, {"citation": True}])
def test_failed_grounding_policy_or_citations_keeps_exact_validated_backend_result(settings):
    request = payload()
    result = compose_action(request, service(ComposerGateway(**settings)))
    assert result.answer == request.response.answer
    assert result.audit["post_action_composed"] is False
    assert result.audit["composition_fallback_code"].startswith(("ACTION_COMPOSITION_", "UNAPPROVED_"))
    assert result.audit["model_call_count"] > 0
    assert not result.audit.get("presentation_rewritten")


def test_only_successfully_reviewed_rendered_referents_replace_prior_order():
    request = payload()
    prior = {"subject": "old option", "agent": "budget", "source_quote": "200",
             "source_position": 1, "option_index": 1}
    request.response.audit["turn_decision"] = {"referents": [prior]}
    new = {**prior, "subject": "SGD 200"}
    gateway = ComposerGateway(referents=[new, {**new, "subject": "not in the answer"}])
    result = compose_action(request, service(gateway))
    assert result.audit["presentation_rewritten"] is True
    assert result.audit["turn_decision"]["referents"] == [{**new, "education_topics": []}]
    assert gateway.requests[1][1]["proposed_referents"] == result.audit["turn_decision"]["referents"]
    failed = compose_action(request, service(ComposerGateway(blocked=True, referents=[new])))
    assert failed.audit["turn_decision"]["referents"] == [prior]
    assert not failed.audit.get("presentation_rewritten")


def test_bedrock_composition_has_scoped_timeouts_and_no_sdk_retries(monkeypatch):
    captured = []
    fixture = ComposerGateway()

    class Client:
        def converse(self, **kwargs):
            text = fixture.generate(system_prompt=kwargs["system"][0]["text"],
                                    user_prompt=kwargs["messages"][0]["content"][0]["text"])
            return {"output": {"message": {"content": [{"text": text}]}}}

    def client(service_name, **kwargs):
        assert service_name == "bedrock-runtime"
        captured.append(kwargs["config"])
        return Client()

    monkeypatch.setattr(boto3, "client", client)
    configured = Settings(MODEL_PROVIDER="bedrock", MODEL_READ_TIMEOUT_SECONDS=60, _env_file=None)
    original = BedrockModelGateway(configured)
    orchestrator = AgentOrchestrator(config=configured, gateway=original)
    result = compose_action(payload(), orchestrator)
    assert result.audit["post_action_composed"] is True
    assert all(6 < config.read_timeout <= 24 for config in captured)
    assert all(config.connect_timeout == 1 for config in captured)
    assert all(config.retries["total_max_attempts"] == 1 for config in captured)
    assert original.settings.model_read_timeout_seconds == 60


def test_composition_risk_window_uses_remaining_total_deadline(monkeypatch):
    from app.core import action_composition
    from app.models.gateway import ModelGatewayError

    clock = iter([0.0, 0.0, 6.0, 12.0, 25.0])
    monkeypatch.setattr(action_composition, "perf_counter", lambda: next(clock))
    captured = []

    def generate(delegate, **kwargs):
        captured.append(delegate.settings.model_read_timeout_seconds)
        assert delegate._total_max_attempts == 1
        return "{}"

    monkeypatch.setattr(BedrockModelGateway, "generate", generate)
    settings = Settings(MODEL_PROVIDER="bedrock", MODEL_READ_TIMEOUT_SECONDS=15, _env_file=None)
    gateway = action_composition.CompositionGateway(
        BedrockModelGateway(settings), settings, stage_read_timeout=15,
    )
    for role in ["response_composer", "action_grounding_review", "risk_compliance"]:
        gateway.generate(system_prompt="PROMPT_ID: " + role, user_prompt="{}", temperature=0, max_tokens=100)
    assert captured == [15, 15, 12]
    with pytest.raises(ModelGatewayError, match="deadline exhausted"):
        gateway.generate(system_prompt="PROMPT_ID: risk_compliance", user_prompt="{}", temperature=0, max_tokens=100)
    assert len(captured) == 3


def test_offline_contract_path_does_not_claim_semantic_quality():
    request = payload()
    result = compose_action(request, service(LocalFixtureModelGateway()))
    assert result.answer == request.response.answer
    assert result.audit["composition_validation_mode"] == "offline_fixture_contract"


def test_composition_endpoint_requires_private_service_authentication():
    result = TestClient(app).post("/coach/compose", json=payload().model_dump(mode="json"))
    assert result.status_code == 401


def test_policy_retrieval_failure_keeps_backend_answer_and_all_consumed_calls():
    class UnavailablePolicy:
        def retrieve(self, *args, **kwargs):
            raise RetrievalError("Policy unavailable", component="policy_retriever")

    request = payload()
    prior_call = {"component": "router", "status": "completed", "total_tokens": 10,
                  "input_tokens": 6, "output_tokens": 4}
    request.response.audit["model_calls"] = [prior_call]
    gateway = ComposerGateway()
    orchestrator = service(gateway)
    orchestrator.policy_retriever = UnavailablePolicy()

    result = compose_action(request, orchestrator)

    assert result.answer == request.response.answer
    assert result.audit["post_action_composed"] is False
    assert result.audit["composition_fallback_code"] == "RETRIEVAL_ERROR"
    assert len(gateway.requests) == 2
    assert result.audit["model_call_count"] == 3
    assert result.audit["model_calls"][0] == prior_call
    assert [item["component"] for item in result.audit["model_calls"][1:]] == [
        "response_composer", "action_grounding_review",
    ]
    assert result.audit["model_input_tokens"] >= 6
    assert result.audit["model_output_tokens"] >= 4


def test_composition_stream_retains_linked_content_free_events_and_rejects_identity():
    from uuid import uuid4

    from app.core.config import settings
    from app.main import get_orchestrator

    trace_id = str(uuid4())
    value = payload().model_dump(mode="json")
    value["response"]["audit"]["trace_id"] = trace_id
    previous = app.dependency_overrides.get(get_orchestrator)
    app.dependency_overrides[get_orchestrator] = lambda: service(ComposerGateway())
    try:
        client = TestClient(app)
        headers = {"X-API-Key": settings.api_key, "X-Workflow-ID": trace_id}
        result = client.post("/coach/compose/stream", headers=headers, json=value)
        assert result.status_code == 200
        frames = [json.loads(line) for line in result.text.splitlines()]
        assert frames[-1]["type"] == "response"
        events = [f["event"] for f in frames if f["type"] == "event"]
        assert all(e["trace_id"] == trace_id for e in events)
        assert any(e["event_type"] == "composition.completed" for e in events)
        assert any(e["event_type"] == "model.decision.accepted" for e in events)
        assert "200 for savings" not in json.dumps(events)
        value["response"]["audit"]["trace_id"] = str(uuid4())
        assert client.post("/coach/compose/stream", headers=headers, json=value).status_code == 422
        assert client.post("/coach/compose/stream", json=value).status_code == 401
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_orchestrator, None)
        else:
            app.dependency_overrides[get_orchestrator] = previous
