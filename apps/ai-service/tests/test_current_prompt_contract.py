import json

import pytest
from coach_trace import safe_details

from app.core.config import Settings
from app.core.financial_grounding import FinancialGroundingSnapshot
from app.core.prompts import CURRENT_PROMPT_VERSION, PromptCatalog
from app.core.schemas import AgentTask, CoachRequest
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator


def test_catalog_has_no_historical_selector_and_config_asserts_packaged_identity():
    assert (
        PromptCatalog().version
        == Settings(_env_file=None).prompt_set_version
        == CURRENT_PROMPT_VERSION
    )
    with pytest.raises(TypeError):
        PromptCatalog("retired")
    with pytest.raises(ValueError, match="requires PROMPT_SET_VERSION"):
        Settings(_env_file=None, PROMPT_SET_VERSION="retired")


def test_effective_hash_ignores_json_formatting_but_detects_instruction_changes(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"version": CURRENT_PROMPT_VERSION}))
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps({"example": "First instruction."}))
    before = PromptCatalog(root=tmp_path)
    path.write_text(json.dumps({"example": "First instruction."}, indent=4))
    assert PromptCatalog(root=tmp_path).content_hash == before.content_hash
    path.write_text(json.dumps({"example": "Changed instruction."}))
    assert PromptCatalog(root=tmp_path).content_hash != before.content_hash


def test_same_release_changed_instructions_invalidate_financial_repair():
    catalog = PromptCatalog()
    task = AgentTask(agent="budget", sanitized_message="Explain my saved allocation.")
    snapshot = FinancialGroundingSnapshot.capture(
        task, {"savings": 1600}, prompt_content_hash=catalog.content_hash
    )
    catalog._prompts["agent_budget"] += "\nChanged qualification instructions."
    with pytest.raises(ModelGatewayError, match="authority changed"):
        snapshot.for_repair(task, prompt_content_hash=catalog.content_hash)


def test_audit_and_content_free_trace_retain_prompt_and_build_identity():
    config = Settings(_env_file=None, MODEL_PROVIDER="local_fixture", BUILD_COMMIT="a" * 40)
    service = AgentOrchestrator(config=config)
    response = service.handle(
        CoachRequest(
            user_id="synthetic", session_id="identity", message="Explain budgeting in general."
        )
    )
    identity = service.prompts.identity(config.build_commit)
    assert {key: response.audit[key] for key in identity} == identity
    assert safe_details(identity) == identity
