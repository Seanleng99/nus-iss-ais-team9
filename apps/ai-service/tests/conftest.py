import pytest

from app.orchestrator import AgentOrchestrator


@pytest.fixture
def force_model_synthesis(monkeypatch):
    """Exercise synthesis safety even when production can preserve specialists."""
    monkeypatch.setattr(AgentOrchestrator, "_can_preserve_specialist_answers", lambda self, state: False)
