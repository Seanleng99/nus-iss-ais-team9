import json

import pytest

from infra.scripts.verify_ecs_task_config import (
    load_container_environment,
    parse_expected,
    verify_environment,
)


def test_loads_named_container_environment(tmp_path) -> None:
    task = tmp_path / "task.json"
    task.write_text(
        json.dumps(
            {
                "containerDefinitions": [
                    {
                        "name": "ai-service",
                        "environment": [
                            {"name": "PROMPT_SET_VERSION", "value": "v4"},
                            {"name": "RAG_PROVIDER", "value": "bedrock"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_container_environment(task, "ai-service") == {
        "PROMPT_SET_VERSION": "v4",
        "RAG_PROVIDER": "bedrock",
    }


def test_reports_mismatched_and_missing_configuration() -> None:
    errors = verify_environment(
        {"PROMPT_SET_VERSION": "v2"},
        {"PROMPT_SET_VERSION": "v4", "RAG_PROVIDER": "bedrock"},
        {"EDUCATION_KNOWLEDGE_BASE_ID"},
    )

    assert len(errors) == 3
    assert any("PROMPT_SET_VERSION" in item for item in errors)
    assert any("RAG_PROVIDER" in item for item in errors)
    assert any("EDUCATION_KNOWLEDGE_BASE_ID" in item for item in errors)


def test_parse_expected_rejects_values_without_separator() -> None:
    with pytest.raises(ValueError, match="NAME=VALUE"):
        parse_expected(["PROMPT_SET_VERSION"])
