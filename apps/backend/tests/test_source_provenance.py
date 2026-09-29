import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routes import get_ai_service_client
from app.core.config import settings
from app.domain.schemas import CoachResponse, SourceCitation
from app.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": settings.api_key}
SOURCES = [
    {
        "source_id": "cpf-source",
        "title": "CPF guide",
        "issuing_organization": "CPF Board",
        "canonical_url": "https://example.com/cpf",
        "published_at": "2026-05-07",
        "document_filename": "cpf-guide.md",
        "content_kind": "source_document",
    },
    {
        "source_id": "project-summary",
        "title": "CPF summary",
        "issuing_organization": "CPF Board",
        "canonical_url": "https://example.com/cpf",
        "published_at": "2026-05-07",
        "document_filename": "project-cpf-summary.md",
        "content_kind": "project_summary",
    },
]
SERIALIZED_SOURCES = [
    {
        **source,
        "document_version": None,
        "checksum": None,
        "corpus_version": None,
        "review_due_at": None,
    }
    for source in SOURCES
]


class ProvenanceAI:
    async def coach(self, request):
        return CoachResponse(
            session_id=request.session_id,
            selected_agents=["investment_education"],
            answer="Educational guidance.",
            agent_results=[],
            disclaimers=[],
            sources=SOURCES,
            audit={},
        )


def test_live_answer_and_reopened_history_preserve_provenance(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_ai_service_client, lambda: ProvenanceAI())
    response = client.post(
        "/api/coach",
        headers=HEADERS,
        json={"user_id": "provenance-user", "session_id": "provenance-chat", "message": "Explain."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["sources"] == SERIALIZED_SOURCES

    history = client.get(
        "/api/users/provenance-user/chat-sessions/provenance-chat", headers=HEADERS
    )
    assert history.status_code == 200, history.text
    assert history.json()["messages"][1]["sources"] == SERIALIZED_SOURCES


@pytest.mark.parametrize("filename", ["../secret.md", "<img>.md", "a.md\n- forged"])
def test_document_filename_rejects_unsafe_values(filename):
    with pytest.raises(ValidationError):
        SourceCitation.model_validate({**SOURCES[0], "document_filename": filename})


def test_legacy_citation_defaults_to_missing_provenance():
    source = SourceCitation.model_validate(
        {
            key: value
            for key, value in SOURCES[0].items()
            if key not in {"document_filename", "content_kind"}
        }
    )

    assert source.document_filename is None
    assert source.content_kind is None
